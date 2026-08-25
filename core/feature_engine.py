"""特征工程模块：将捐精人原始数据编码为特征向量。"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

# ============ 枚举映射（对齐《文本信息》取值） ============

EDUCATION_MAP = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}

FIGURE_CATEGORIES = ["一般", "瘦弱", "强壮", "肥胖", "匀称型", "精壮型", "偏瘦型"]
SKIN_COLOR_CATEGORIES = ["偏白", "一般", "偏黑"]
BLOOD_TYPE_CATEGORIES = ["A", "B", "O", "AB"]
FACE_SHAPE_CATEGORIES = ["长方", "长", "椭圆", "瓜子", "圆", "方", "菱形"]
EYELID_CATEGORIES = ["单", "双", "内双"]
LIP_SHAPE_CATEGORIES = ["一般", "厚", "薄", "厚唇", "薄唇", "适中"]
CONSTELLATION_CATEGORIES = [
    "白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
    "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座",
]
RH_BLOOD_CATEGORIES = ["阳性", "阴性", "+", "-"]


def _one_hot(value, categories: list[str]) -> list[float]:
    """独热/多热编码：支持单值(str)或多值(list)，未匹配则全零。"""
    vec = [0.0] * len(categories)
    vals = value if isinstance(value, list) else [value] if value else []
    for v in vals:
        if v in categories:
            vec[categories.index(v)] = 1.0
    return vec


def _bmi_col(df: pd.DataFrame) -> str:
    if "BMI" in df.columns:
        return "BMI"
    return "体征指数"


def _blood_col(row_or_df) -> str:
    cols = getattr(row_or_df, "columns", None) or getattr(row_or_df, "index", [])
    if "ABO血型" in cols:
        return "ABO血型"
    return "血型"


def _rh_col(row_or_df) -> str:
    cols = getattr(row_or_df, "columns", None) or getattr(row_or_df, "index", [])
    if "Rh血型" in cols:
        return "Rh血型"
    return "RH血型"


def _lip_col(row_or_df) -> str:
    cols = getattr(row_or_df, "columns", None) or getattr(row_or_df, "index", [])
    if "唇型" in cols:
        return "唇型"
    return "唇形"


class FeatureEncoder:
    """捐精人特征编码器。"""

    def __init__(self, df: pd.DataFrame):
        self.df = df if df is not None and len(df) else pd.DataFrame(
            {"身高": [170], "BMI": [22], "体重": [70]}
        )
        self._empty_source = df is None or len(df) == 0
        self.height_scaler = MinMaxScaler()
        self.bmi_scaler = MinMaxScaler()
        self.weight_scaler = MinMaxScaler()
        self._fit_scalers()
        self.feature_matrix: np.ndarray | None = None
        self.feature_names: list[str] = []

    def _fit_scalers(self):
        bmi_c = _bmi_col(self.df)
        h = self.df[["身高"]].fillna(170).astype(float).values
        b = self.df[[bmi_c]].fillna(22).astype(float).values
        w = self.df[["体重"]].fillna(70).astype(float).values
        self.height_scaler.fit(h)
        self.bmi_scaler.fit(b)
        self.weight_scaler.fit(w)

    def encode_donor(self, row: pd.Series) -> np.ndarray:
        features = []
        bmi_c = "BMI" if "BMI" in row.index else "体征指数"
        blood_c = _blood_col(row)
        rh_c = _rh_col(row)
        lip_c = _lip_col(row)

        edu_val = EDUCATION_MAP.get(str(row.get("学历", "")), 0)
        features.append(edu_val / 4.0)

        h = self.height_scaler.transform([[float(row.get("身高", 170) or 170)]])[0][0]
        features.append(h)

        bmi = self.bmi_scaler.transform([[float(row.get(bmi_c, 22) or 22)]])[0][0]
        features.append(bmi)

        w = self.weight_scaler.transform([[float(row.get("体重", 70) or 70)]])[0][0]
        features.append(w)

        features.extend(_one_hot(str(row.get("体型", "")), FIGURE_CATEGORIES))
        features.extend(_one_hot(str(row.get("肤色", "")), SKIN_COLOR_CATEGORIES))
        features.extend(_one_hot(str(row.get(blood_c, "")), BLOOD_TYPE_CATEGORIES))
        features.extend(_one_hot(str(row.get("脸型", "")), FACE_SHAPE_CATEGORIES))
        features.extend(_one_hot(str(row.get("眼皮", "")), EYELID_CATEGORIES))
        features.extend(_one_hot(str(row.get(lip_c, "")), LIP_SHAPE_CATEGORIES))
        features.extend(_one_hot(str(row.get("星座", "")), CONSTELLATION_CATEGORIES))
        features.extend(_one_hot(str(row.get(rh_c, "")), RH_BLOOD_CATEGORIES))

        return np.array(features, dtype=np.float64)

    def encode_all(self) -> np.ndarray:
        if self._empty_source or len(self.df) == 0:
            dim = (
                4
                + len(FIGURE_CATEGORIES)
                + len(SKIN_COLOR_CATEGORIES)
                + len(BLOOD_TYPE_CATEGORIES)
                + len(FACE_SHAPE_CATEGORIES)
                + len(EYELID_CATEGORIES)
                + len(LIP_SHAPE_CATEGORIES)
                + len(CONSTELLATION_CATEGORIES)
                + len(RH_BLOOD_CATEGORIES)
            )
            self.feature_matrix = np.zeros((0, dim))
            self.feature_names = (
                ["education", "height", "bmi", "weight"]
                + [f"figure_{c}" for c in FIGURE_CATEGORIES]
                + [f"skin_{c}" for c in SKIN_COLOR_CATEGORIES]
                + [f"blood_{c}" for c in BLOOD_TYPE_CATEGORIES]
                + [f"face_{c}" for c in FACE_SHAPE_CATEGORIES]
                + [f"eyelid_{c}" for c in EYELID_CATEGORIES]
                + [f"lip_{c}" for c in LIP_SHAPE_CATEGORIES]
                + [f"const_{c}" for c in CONSTELLATION_CATEGORIES]
                + [f"rh_{c}" for c in RH_BLOOD_CATEGORIES]
            )
            return self.feature_matrix

        vectors = [self.encode_donor(row) for _, row in self.df.iterrows()]
        self.feature_matrix = np.array(vectors)
        self.feature_names = (
            ["education", "height", "bmi", "weight"]
            + [f"figure_{c}" for c in FIGURE_CATEGORIES]
            + [f"skin_{c}" for c in SKIN_COLOR_CATEGORIES]
            + [f"blood_{c}" for c in BLOOD_TYPE_CATEGORIES]
            + [f"face_{c}" for c in FACE_SHAPE_CATEGORIES]
            + [f"eyelid_{c}" for c in EYELID_CATEGORIES]
            + [f"lip_{c}" for c in LIP_SHAPE_CATEGORIES]
            + [f"const_{c}" for c in CONSTELLATION_CATEGORIES]
            + [f"rh_{c}" for c in RH_BLOOD_CATEGORIES]
        )
        return self.feature_matrix

    def encode_query(self, parsed_features: dict) -> tuple[np.ndarray, np.ndarray]:
        features = []
        mask = []

        edu = parsed_features.get("education")
        edu_list = edu if isinstance(edu, list) else [edu] if edu else []
        edu_valid = [e for e in edu_list if e in EDUCATION_MAP]
        specified = bool(edu_valid)
        features.append(max(EDUCATION_MAP[e] for e in edu_valid) / 4.0 if specified else 0.5)
        mask.append(specified)

        height_spec = parsed_features.get("height")
        h_specified = bool(
            height_spec and isinstance(height_spec, dict) and (height_spec.get("min") or height_spec.get("max"))
        )
        if h_specified:
            h_min = height_spec.get("min") or 165
            h_max = height_spec.get("max") or 190
            h_mid = (h_min + h_max) / 2.0
        else:
            h_mid = 175.0
        features.append(self.height_scaler.transform([[h_mid]])[0][0])
        mask.append(h_specified)

        bmi_spec = parsed_features.get("bmi")
        bmi_specified = bool(bmi_spec)
        features.append(
            self.bmi_scaler.transform([[float(bmi_spec)]])[0][0] if bmi_specified else 0.5
        )
        mask.append(bmi_specified)

        weight_spec = parsed_features.get("weight")
        w_specified = bool(weight_spec)
        features.append(
            self.weight_scaler.transform([[float(weight_spec)]])[0][0] if w_specified else 0.5
        )
        mask.append(w_specified)

        for key, categories in [
            ("figure", FIGURE_CATEGORIES),
            ("skin_color", SKIN_COLOR_CATEGORIES),
            ("blood_type", BLOOD_TYPE_CATEGORIES),
            ("face_shape", FACE_SHAPE_CATEGORIES),
            ("eyelid", EYELID_CATEGORIES),
            ("lip_shape", LIP_SHAPE_CATEGORIES),
            ("constellation", CONSTELLATION_CATEGORIES),
            ("rh_blood", RH_BLOOD_CATEGORIES),
        ]:
            val = parsed_features.get(key)
            val_list = val if isinstance(val, list) else [val] if val else []
            specified = any(v in categories for v in val_list)
            oh = _one_hot(val or "", categories)
            features.extend(oh)
            mask.extend([specified] * len(categories))

        return np.array(features, dtype=np.float64), np.array(mask, dtype=bool)

    def get_feature_dimension(self) -> int:
        if self.feature_matrix is not None:
            return self.feature_matrix.shape[1]
        return len(self.feature_names) if self.feature_names else 0
