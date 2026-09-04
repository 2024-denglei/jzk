# V2 Ranker on PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default `/api/match` ranker with the classmate V2 rule score + monotonic calibrator, while must-filtering and donor rows still come from PostgreSQL `donor.donors`.

**Architecture:** Keep `parse_profile` and `build_hard_filter_sql`. Add mapping helpers plus a vendored inference package under `core/preference/v2/`. `V2CalibratedRanker` implements `Ranker.rank` with batch model inference over **all** SQL-filtered rows (no 300 cap). `match_profile` defaults to that ranker; load failure surfaces as HTTP 503. Do not call the CSV FastAPI service.

**Tech Stack:** FastAPI, PostgreSQL, PyTorch (`torch>=2.2,<3`), existing PreferenceProfile, classmate `best_model_v2.pt` (legacy `model_state_dict` + `context_mean`/`context_std`).

## Global Constraints

- HTTP path stays `POST /api/match`; JWT unchanged.
- Do not read CSV at runtime; no Profile CSV for scaler.
- Do not silently fall back to `HeuristicRanker`.
- `top_k==0` returns all ranked rows; `top_k>0` slices the response only.
- Keyword attributes stay substring match (`type=keyword`).
- `POST /api/search` unchanged.
- Do not commit unless the user explicitly asks (user rule). Skip commit steps during execution.

## File map

| Path | Responsibility |
|---|---|
| `core/preference/v2_adapter.py` | PreferenceProfile → V2 spec; DB row → scoring dict |
| `core/preference/v2/` | Vendored scoring, model, features, settings, predict, load |
| `core/preference/v2_ranker.py` | `V2CalibratedRanker`, engine singleton, `V2RankerUnavailable` |
| `core/preference/pipeline.py` | Default ranker, `match_pct` from model score |
| `api/match.py` | Map `V2RankerUnavailable` → 503 |
| `config.py` / `.env.example` | Checkpoint paths |
| `models/best_model_v2.pt` | Copied weights |
| `requirements.txt` | `torch>=2.2,<3` |
| `tests/preference/test_v2_adapter.py` | Mapping tests |
| `tests/preference/test_v2_ranker.py` | Ranker + no-predict on empty |
| `tests/test_match_api.py` | 503 when model missing |

---

### Task 1: Profile and DB-row mapping

**Files:**
- Create: `core/preference/v2_adapter.py`
- Test: `tests/preference/test_v2_adapter.py`

**Interfaces:**
- Consumes: `PreferenceProfile`, `RangeAttr`, `EnumAttr`, `KeywordAttr` from `core.preference.schema`; `_calc_age`, `normalize_rh` from existing modules
- Produces:
  - `profile_to_v2_spec(profile: PreferenceProfile) -> dict[str, Any]` with keys `schema_version`, `attributes`
  - `donor_row_to_v2(row: dict[str, Any]) -> dict[str, Any]`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date

from core.preference.v2_adapter import donor_row_to_v2, profile_to_v2_spec
from core.preference.validate import parse_profile


def test_profile_to_v2_keeps_keyword_hometown():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "hometown": {
                "constraint": "must",
                "weight": 1.0,
                "keywords": ["重庆"],
                "match": "any",
            },
            "height_cm": {
                "constraint": "prefer",
                "weight": 0.8,
                "range": {"min": 175, "max": None},
            },
            "abo_blood": {
                "constraint": "must",
                "weight": 1.0,
                "values": ["O"],
            },
        },
    })
    spec = profile_to_v2_spec(profile)
    hometown = spec["attributes"]["hometown"]
    assert hometown["type"] == "keyword"
    assert hometown["keywords"] == ["重庆"]
    assert hometown["match_mode"] == "any"
    assert "values" not in hometown
    assert spec["attributes"]["height_cm"]["type"] == "range"
    assert spec["attributes"]["abo_blood"]["type"] == "enum"


def test_donor_row_age_from_birth_date():
    row = {
        "code": "A1",
        "abo_blood": "O",
        "rh_blood": "+",
        "height_cm": 180,
        "birth_date": date(2000, 1, 1),
        "sideburns": "无",
    }
    out = donor_row_to_v2(row)
    assert out["age"] >= 25
    assert out["rh_blood"] == "阳性"
    assert out["height_cm"] == 180
    assert out["code"] == "A1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd e:\jzk\agent && .venv\Scripts\python.exe -m pytest tests/preference/test_v2_adapter.py -v`

Expected: FAIL with `ModuleNotFoundError: core.preference.v2_adapter` or import error.

- [ ] **Step 3: Implement mapping**

Create `core/preference/v2_adapter.py`:

```python
from __future__ import annotations

from typing import Any

from core.data_loader import _calc_age
from core.preference.schema import EnumAttr, KeywordAttr, PreferenceProfile, RangeAttr
from core.preference.scorer import normalize_rh


def profile_to_v2_spec(profile: PreferenceProfile) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for name, attr in profile.attributes.items():
        if isinstance(attr, RangeAttr):
            attributes[name] = {
                "type": "range",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "range": {"min": attr.range.min, "max": attr.range.max},
            }
        elif isinstance(attr, EnumAttr):
            attributes[name] = {
                "type": "enum",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "values": list(attr.values),
            }
        elif isinstance(attr, KeywordAttr):
            attributes[name] = {
                "type": "keyword",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "keywords": list(attr.keywords),
                "match_mode": attr.match,
            }
        else:
            raise TypeError(f"unsupported attr for {name}")
    return {"schema_version": profile.schema_version, "attributes": attributes}


def donor_row_to_v2(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    age = _calc_age(row.get("birth_date") or row.get("age"))
    out["age"] = age if age else row.get("age")
    if "rh_blood" in out:
        out["rh_blood"] = normalize_rh(out.get("rh_blood"))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd e:\jzk\agent && .venv\Scripts\python.exe -m pytest tests/preference/test_v2_adapter.py -v`

Expected: PASS

---

### Task 2: Vendor V2 inference (no CSV, no FastAPI)

**Files:**
- Create: `core/preference/v2/__init__.py` (empty)
- Copy: `sperm_match_v2_api_local/src/sperm_match_v2/scoring.py` → `core/preference/v2/scoring.py`
- Copy: `sperm_match_v2_api_local/src/sperm_match_v2/model.py` → `core/preference/v2/model.py`
- Copy: `sperm_match_v2_api_local/src/sperm_match_v2/features.py` → `core/preference/v2/features.py`
- Copy: `sperm_match_v2_api_local/src/sperm_match_v2/config.py` → `core/preference/v2/settings.py`
- Copy: `sperm_match_v2_api_local/config_v2.json` → `core/preference/v2/config_v2.json`
- Create: `core/preference/v2/predict.py`
- Create: `core/preference/v2/load.py`
- Modify: vendored files’ relative imports

**Interfaces:**
- Consumes: classmate inference modules
- Produces:
  - `load_v2_engine(checkpoint_path: Path, config_path: Path, force_cpu: bool) -> tuple[model, ContextScaler, AppConfig, device]`
  - `predict_arrays(...)` same signature as classmate `pipeline.predict_arrays`
  - `score_profile_against_donor` from vendored scoring
  - `profile_context_features` from vendored features

- [ ] **Step 1: Copy files and rewrite imports**

From `e:\jzk\agent` (PowerShell):

```powershell
$src = "e:\jzk\sperm_match_v2_api_local\src\sperm_match_v2"
$dst = "e:\jzk\agent\core\preference\v2"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item "$src\scoring.py" "$dst\scoring.py"
Copy-Item "$src\model.py" "$dst\model.py"
Copy-Item "$src\features.py" "$dst\features.py"
Copy-Item "$src\config.py" "$dst\settings.py"
Copy-Item "e:\jzk\sperm_match_v2_api_local\config_v2.json" "$dst\config_v2.json"
Set-Content "$dst\__init__.py" ""
```

Then edit imports:

- `model.py`: `from .config import ModelConfig` → `from .settings import ModelConfig`
- `scoring.py`: `from .config import RuleConfig` → `from .settings import RuleConfig`
- `features.py`: keep `from .scoring import parse_profile`

Create `core/preference/v2/predict.py` by copying only `predict_arrays` from classmate `pipeline.py` (the function starting at `predict_arrays`, including `@torch.inference_mode()`). Change:

```python
from .model import V2MonotonicCalibrator
```

Do not copy training, DataLoader, or CSV paths.

- [ ] **Step 2: Write load.py (use scaler inside the checkpoint, never Profile CSV)**

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from .features import CONTEXT_FEATURE_NAMES, ContextScaler
from .model import V2MonotonicCalibrator
from .settings import AppConfig


def load_v2_engine(
    checkpoint_path: Path,
    config_path: Path,
    force_cpu: bool = True,
):
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"找不到模型文件：{checkpoint_path}")
    device = torch.device("cpu" if force_cpu or not torch.cuda.is_available() else "cuda")
    raw: Any = torch.load(checkpoint_path, map_location=device, weights_only=False)
    config = AppConfig.load(config_path)
    if not isinstance(raw, dict):
        raise TypeError("Checkpoint 必须是 dict")

    if {"context_mean", "context_std", "context_feature_names"} <= set(raw):
        names = list(raw["context_feature_names"])
        if names != list(CONTEXT_FEATURE_NAMES):
            raise ValueError("Checkpoint 上下文字段与当前代码不一致")
        scaler = ContextScaler(
            feature_names=names,
            mean=np.asarray(raw["context_mean"], dtype=np.float64),
            scale=np.asarray(raw["context_std"], dtype=np.float64),
        )
    elif "context_scaler" in raw:
        scaler = ContextScaler.from_dict(raw["context_scaler"])
    else:
        raise KeyError("Checkpoint 缺少 context_mean/std 或 context_scaler")

    state = raw.get("model_state_dict") or raw.get("state_dict")
    if not isinstance(state, dict):
        raise KeyError("Checkpoint 缺少 model_state_dict/state_dict")
    hidden = raw.get("model_hidden_dims")
    if hidden:
        config.model.context_hidden_dims = list(hidden)
    dropout = raw.get("model_dropout")
    if dropout is not None:
        config.model.dropout = float(dropout)
    model = V2MonotonicCalibrator(len(scaler.feature_names), config.model)
    model.load_state_dict(state, strict=True)
    model.to(device).eval()
    return model, scaler, config, device
```

- [ ] **Step 3: Smoke-load the classmate checkpoint**

Run from `e:\jzk\agent` after installing torch in the **agent** venv (Task 5 may be done first if import fails). If torch is not yet installed, skip until Task 5 and continue Task 3 with mocks.

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from core.preference.v2.load import load_v2_engine; p=Path(r'e:\jzk\sperm_match_v2_api_local\best_model_v2.pt'); c=Path('core/preference/v2/config_v2.json'); m,s,cfg,d=load_v2_engine(p,c,True); print(d, type(m).__name__, s.feature_names[0])"
```

Expected: prints `cpu V2MonotonicCalibrator active_attr_count`

---

### Task 3: V2CalibratedRanker

**Files:**
- Create: `core/preference/v2_ranker.py`
- Test: `tests/preference/test_v2_ranker.py`

**Interfaces:**
- Consumes: `profile_to_v2_spec`, `donor_row_to_v2`, `score_profile_against_donor`, `profile_context_features`, `predict_arrays`, `load_v2_engine`, `FieldScore`, `Ranker`
- Produces:
  - `class V2RankerUnavailable(Exception)`
  - `class V2CalibratedRanker(Ranker)`
  - `get_default_ranker() -> Ranker` (lazy singleton; raises `V2RankerUnavailable`)
  - `V2CalibratedRanker.rank(profile, rows) -> list[tuple[dict, float, list[FieldScore]]]`
  - Sort key: model score desc, then heuristic_score desc, then `specimen_count` desc

- [ ] **Step 1: Write failing tests**

```python
from core.preference.v2_ranker import V2CalibratedRanker
from core.preference.validate import parse_profile


def test_rank_all_rows_no_pool_cap(monkeypatch):
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "height_cm": {"constraint": "prefer", "weight": 1.0, "range": {"min": 175}},
        },
    })
    rows = [
        {"code": f"C{i}", "abo_blood": "O", "height_cm": 175 + i, "specimen_count": 1, "birth_date": None}
        for i in range(5)
    ]
    calls = {"n": 0}

    def fake_predict(model, heuristic, mismatch, context, device, batch_size):
        calls["n"] += 1
        import numpy as np
        return {"prediction": np.asarray(heuristic) * 0.99}

    monkeypatch.setattr("core.preference.v2_ranker.predict_arrays", fake_predict)
    ranker = V2CalibratedRanker.__new__(V2CalibratedRanker)
    ranker.model = object()
    ranker.scaler = type("S", (), {
        "transform_mapping": staticmethod(lambda m: __import__("numpy").zeros(len(m), dtype="float32")),
    })()
    ranker.config = type("C", (), {"rules": None, "evaluation": type("E", (), {"prediction_batch_size": 16})()})()
    ranker.device = "cpu"
    out = V2CalibratedRanker.rank(ranker, profile, rows)
    assert len(out) == 5
    assert calls["n"] == 1
    assert out[0][0]["code"] == "C4"
```

`transform_mapping` must return a 1-D vector of context dim (10). Fix the stub to `numpy.zeros(10, dtype=numpy.float32)` so `numpy.repeat` works in rank().

Use this scaler stub instead:

```python
import numpy as np

class _Scaler:
    def transform_mapping(self, mapping):
        return np.zeros(10, dtype=np.float32)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd e:\jzk\agent && .venv\Scripts\python.exe -m pytest tests/preference/test_v2_ranker.py::test_rank_all_rows_no_pool_cap -v`

Expected: FAIL `ModuleNotFoundError` or `V2CalibratedRanker` missing.

- [ ] **Step 3: Implement v2_ranker.py**

```python
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

from core.preference.scorer import FieldScore, Ranker
from core.preference.v2.features import profile_context_features
from core.preference.v2.load import load_v2_engine
from core.preference.v2.predict import predict_arrays
from core.preference.v2.scoring import score_profile_against_donor
from core.preference.v2_adapter import donor_row_to_v2, profile_to_v2_spec


class V2RankerUnavailable(Exception):
    pass


def _parts_from_matches(matches, specs: dict) -> list[FieldScore]:
    parts: list[FieldScore] = []
    for match in matches:
        spec = specs[match.name]
        if spec.get("type") == "range":
            target: Any = dict(spec.get("range") or {})
        elif spec.get("type") == "keyword":
            target = {"keywords": spec.get("keywords"), "match": spec.get("match_mode", "any")}
        else:
            target = list(spec.get("values") or [])
        parts.append(
            FieldScore(
                match.name,
                match.donor_value,
                target,
                float(match.similarity),
                float(match.weight),
                match.constraint,
            )
        )
    return parts


class V2CalibratedRanker(Ranker):
    def __init__(self, model, scaler, config, device):
        self.model = model
        self.scaler = scaler
        self.config = config
        self.device = device

    def score(self, profile, row: dict[str, Any]) -> tuple[float, list[FieldScore]]:
        ranked = self.rank(profile, [row])
        return ranked[0][1], ranked[0][2]

    def rank(self, profile, rows: list[dict[str, Any]]):
        v2_profile = profile_to_v2_spec(profile)
        specs = v2_profile["attributes"]
        heuristics = []
        mismatches = []
        parts_list = []
        for row in rows:
            donor = donor_row_to_v2(row)
            rule = score_profile_against_donor(v2_profile, donor, self.config.rules)
            heuristics.append(rule.heuristic_score)
            mismatches.append(rule.max_weighted_mismatch)
            parts_list.append(_parts_from_matches(rule.feature_matches, specs))
        n = len(rows)
        ctx_map = profile_context_features(
            v2_profile, eligible_after_must=n, selected_candidates=n
        )
        ctx_row = self.scaler.transform_mapping(ctx_map)
        context = np.repeat(ctx_row.reshape(1, -1), n, axis=0)
        arrays = predict_arrays(
            self.model,
            np.asarray(heuristics, dtype=np.float32),
            np.asarray(mismatches, dtype=np.float32),
            context,
            self.device,
            self.config.evaluation.prediction_batch_size,
        )
        preds = [float(x) for x in arrays["prediction"].tolist()]
        indexed = list(zip(rows, preds, parts_list, heuristics))
        indexed.sort(
            key=lambda t: (t[1], t[3], float(t[0].get("specimen_count") or 0)),
            reverse=True,
        )
        return [(row, score, parts) for row, score, parts, _h in indexed]


_LOCK = threading.Lock()
_RANKER: V2CalibratedRanker | None = None
_LOAD_ERROR: V2RankerUnavailable | None = None


def get_default_ranker() -> Ranker:
    global _RANKER, _LOAD_ERROR
    if _RANKER is not None:
        return _RANKER
    if _LOAD_ERROR is not None:
        raise _LOAD_ERROR
    with _LOCK:
        if _RANKER is not None:
            return _RANKER
        if _LOAD_ERROR is not None:
            raise _LOAD_ERROR
        try:
            root = Path(__file__).resolve().parents[2]
            ckpt = Path(os.getenv("V2_CHECKPOINT_PATH", str(root / "models" / "best_model_v2.pt")))
            cfg = Path(os.getenv("V2_CONFIG_PATH", str(root / "core" / "preference" / "v2" / "config_v2.json")))
            force_cpu = os.getenv("V2_FORCE_CPU", "1").strip().lower() in {"1", "true", "yes"}
            model, scaler, config, device = load_v2_engine(ckpt, cfg, force_cpu=force_cpu)
            _RANKER = V2CalibratedRanker(model, scaler, config, device)
            return _RANKER
        except Exception as exc:
            _LOAD_ERROR = V2RankerUnavailable(str(exc))
            raise _LOAD_ERROR from exc
```

`Path(__file__).parents[2]` is `agent/` (file is `agent/core/preference/v2_ranker.py` → parents[0]=preference, [1]=core, [2]=agent). Correct.

- [ ] **Step 4: Run ranker unit test**

Run: `cd e:\jzk\agent && .venv\Scripts\python.exe -m pytest tests/preference/test_v2_ranker.py -v`

Expected: PASS. `score_profile_against_donor` will run for real (needs vendored scoring). Taller donors get higher heuristic, fake predict preserves order.

---

### Task 4: Wire pipeline, match_pct, HTTP 503

**Files:**
- Modify: `core/preference/pipeline.py` (`ranker = ranker or HeuristicRanker()` and `_candidate_dict` match_pct)
- Modify: `api/match.py` (`execute_match`)
- Modify: `tests/preference/test_pipeline.py` (`test_ranks_by_score` pass `HeuristicRanker()`)
- Modify: `tests/test_match_api.py` (503 test)

**Interfaces:**
- Consumes: `get_default_ranker`, `V2RankerUnavailable`
- Produces: default `match_profile` uses V2; `match_pct = round(100 * score, 2)`; 503 on load failure

- [ ] **Step 1: Write 503 test**

Add to `tests/test_match_api.py`:

```python
def test_match_returns_503_when_ranker_unavailable(monkeypatch):
    from core.preference.v2_ranker import V2RankerUnavailable

    def boom(*args, **kwargs):
        raise V2RankerUnavailable("找不到模型文件")

    monkeypatch.setattr("api.match.match_profile", boom)
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": VALID_PROFILE},
        headers=_auth_headers(),
    )
    assert res.status_code == 503
    assert "模型" in str(res.json()["detail"]) or "找不到" in str(res.json()["detail"])
```

Better: monkeypatch `get_default_ranker` inside `match_profile` after wiring. Until pipeline calls `get_default_ranker`, patch `execute_match` path:

In `execute_match`:

```python
from core.preference.v2_ranker import V2RankerUnavailable, get_default_ranker

def execute_match(...):
    try:
        profile = parse_profile(raw_profile)
        kwargs = dict(match_kwargs)
        if "ranker" not in kwargs:
            kwargs["ranker"] = get_default_ranker()
        result = match_profile(profile, **kwargs)
    except V2RankerUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
```

Then 503 test:

```python
def test_match_returns_503_when_ranker_unavailable(monkeypatch):
    from core.preference.v2_ranker import V2RankerUnavailable

    monkeypatch.setattr(
        "api.match.get_default_ranker",
        lambda: (_ for _ in ()).throw(V2RankerUnavailable("找不到模型文件")),
    )
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": VALID_PROFILE},
        headers=_auth_headers(),
    )
    assert res.status_code == 503
```

Existing tests that call `/api/match` and reach `match_profile` without mock must still work: `test_empty_profile_skips_query` never needs ranker (empty attributes). Tests that mock `match_profile` unchanged.

`test_match_api.py` tests that call real `execute_match` with a non-empty profile will load V2 after this task — copy the checkpoint in Task 5 before running the full file, or keep those tests mocked.

Check `test_match_api.py` for un-mocked `execute_match` with attributes: if any call real `match_profile` with rows, they need HeuristicRanker or checkpoint.

- [ ] **Step 2: Run 503 test expecting fail (no handler yet)**

Run: `pytest tests/test_match_api.py::test_match_returns_503_when_ranker_unavailable -v`

Expected: FAIL (503 test missing or still 500).

- [ ] **Step 3: Pipeline + match.py changes**

`pipeline.py`:

```python
from core.preference.scorer import FieldScore, HeuristicRanker, Ranker
```

Change `_candidate_dict`:

```python
    return {
        "donor_info": get_donor_display_info(row),
        "score": round(float(score), 4),
        "match_pct": round(100 * float(score), 2),
        ...
```

Keep `match_level` on each candidate as:

```python
        "match_level": (
            "full"
            if parts and all(p.s >= 1.0 - 1e-9 for p in parts)
            else "high" if score >= 0.85
            else "medium" if score >= 0.70
            else "low"
        ),
```

For empty parts, use `"none"` only when there are no parts; if parts exist and not all match, use the score buckets above.

`match_profile`:

```python
    if ranker is None:
        from core.preference.v2_ranker import get_default_ranker
        ranker = get_default_ranker()
```

Do **not** call `get_default_ranker` when `not profile.attributes` or when `not rows` — current code already returns before `ranker.rank`. Still avoid constructing ranker on skip/zero-row: only call `get_default_ranker` when `rows` is non-empty.

```python
    sql, params = build_hard_filter_sql(profile)
    rows = fetch(sql, params)
    if not rows:
        ...
    if ranker is None:
        from core.preference.v2_ranker import get_default_ranker
        ranker = get_default_ranker()
    ranked = ranker.rank(profile, rows)
```

`test_ranks_by_score`: add `from core.preference.scorer import HeuristicRanker` and `ranker=HeuristicRanker()`.

`execute_match` catch `V2RankerUnavailable` → 503 as above. Import `get_default_ranker` only if execute_match injects ranker; alternatively let `match_profile` raise and catch in `match_donors`/`execute_match`:

```python
def execute_match(...):
    from core.preference.v2_ranker import V2RankerUnavailable
    try:
        profile = parse_profile(raw_profile)
        result = match_profile(profile, **match_kwargs)
        ...
    except V2RankerUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
```

If `match_donors` already has try/except for `ProfileValidationError`, add `V2RankerUnavailable` there too so both HTTP and `invoke_match_endpoint` ASGI see 503.

```python
@router.post("/api/match")
async def match_donors(...):
    try:
        return execute_match(body.profile, top_k=body.top_k, log=True)
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except V2RankerUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
```

And `execute_match` re-raises `V2RankerUnavailable` (do not swallow).

- [ ] **Step 4: Run targeted tests**

Run:

```
pytest tests/preference/test_pipeline.py tests/test_match_api.py::test_match_returns_503_when_ranker_unavailable tests/test_match_api.py::test_empty_profile_skips_query -v
```

Expected: PASS

---

### Task 5: Checkpoint, torch, env

**Files:**
- Create: `models/best_model_v2.pt` (copy)
- Modify: `requirements.txt`
- Modify: `config.py`
- Modify: `.env.example`

- [ ] **Step 1: Copy weights and add torch**

```powershell
New-Item -ItemType Directory -Force -Path "e:\jzk\agent\models" | Out-Null
Copy-Item "e:\jzk\sperm_match_v2_api_local\best_model_v2.pt" "e:\jzk\agent\models\best_model_v2.pt"
```

Add to `requirements.txt`:

```
torch>=2.2,<3
```

Install into agent venv:

```
e:\jzk\agent\.venv\Scripts\python.exe -m pip install "torch>=2.2,<3"
```

- [ ] **Step 2: config + env example**

In `config.py`:

```python
_AGENT_ROOT = os.path.dirname(__file__)
V2_CHECKPOINT_PATH = os.getenv(
    "V2_CHECKPOINT_PATH",
    os.path.join(_AGENT_ROOT, "models", "best_model_v2.pt"),
)
V2_CONFIG_PATH = os.getenv(
    "V2_CONFIG_PATH",
    os.path.join(_AGENT_ROOT, "core", "preference", "v2", "config_v2.json"),
)
V2_FORCE_CPU = os.getenv("V2_FORCE_CPU", "1").strip().lower() in {"1", "true", "yes"}
```

Point `get_default_ranker` at `config.V2_CHECKPOINT_PATH` / `V2_CONFIG_PATH` / `V2_FORCE_CPU` instead of duplicating env parsing.

`.env.example` append:

```
# V2 排序模型（默认 models/best_model_v2.pt，CPU）
# V2_CHECKPOINT_PATH=
# V2_CONFIG_PATH=
# V2_FORCE_CPU=1
```

- [ ] **Step 3: Integration test with real weights (no live DB)**

Add `tests/preference/test_v2_ranker_checkpoint.py`:

```python
from pathlib import Path

from core.preference.v2_ranker import V2CalibratedRanker, get_default_ranker
from core.preference.validate import parse_profile

def test_checkpoint_ranks_taller_higher():
    ranker = get_default_ranker()
    assert isinstance(ranker, V2CalibratedRanker)
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "education": {"constraint": "prefer", "weight": 0.7, "values": ["硕士", "博士"]},
            "height_cm": {"constraint": "prefer", "weight": 0.8, "range": {"min": 175, "max": None}},
        },
    })
    rows = [
        {"code": "SHORT", "abo_blood": "O", "education": "硕士", "height_cm": 175, "specimen_count": 1},
        {"code": "TALL", "abo_blood": "O", "education": "硕士", "height_cm": 195, "specimen_count": 1},
    ]
    out = ranker.rank(profile, rows)
    assert out[0][0]["code"] == "TALL"
    assert out[0][1] >= out[1][1]
```

Run: `pytest tests/preference/test_v2_ranker_checkpoint.py tests/preference/test_v2_adapter.py tests/preference/test_v2_ranker.py tests/preference/test_pipeline.py tests/test_match_api.py -v`

Expected: PASS

Optional live check (not required for CI if DB down): JWT + `docs/samples/match-api-request.json` against running `8010` `/api/match`; `filtered_count` equals active O-type count in Postgres, not CSV 1168.

---

### Task 6: Search regression + spec status

**Files:**
- Modify: `docs/superpowers/specs/2026-08-25-v2-ranker-postgres-design.md` status → 已实现
- Test: existing search tests

- [ ] **Step 1: Run search + preference suites**

```
cd e:\jzk\agent
.\.venv\Scripts\python.exe -m pytest tests/preference tests/test_match_api.py tests/test_search.py -v
```

If `tests/test_search.py` does not exist, run `pytest tests -k search -v`.

Expected: PASS; `/api/search` behavior unchanged.

- [ ] **Step 2: Flip spec status to 已实现**

Change the spec header `状态：待实现` → `状态：已实现`.

---

## Spec coverage

| Spec item | Task |
|---|---|
| Ranker in agent, SQL must filter | 3, 4 |
| All filtered rows into model | 3 |
| Keyword hometown | 1 |
| age from birth_date | 1 |
| Checkpoint scaler, no Profile CSV | 2 |
| 503 no heuristic fallback | 4 |
| top_k slice only in `execute_match` (existing) | 4 (unchanged slice) |
| torch + models/best_model_v2.pt | 5 |
| search unchanged | 6 |
| donor_info from get_donor_display_info | 4 (pipeline unchanged) |
| match_pct from model score | 4 |
| MATCH_API_URL still external bypass | no code change |

## Type names (locked)

`profile_to_v2_spec`, `donor_row_to_v2`, `V2CalibratedRanker`, `V2RankerUnavailable`, `get_default_ranker`, `load_v2_engine`
