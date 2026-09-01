"""旧 JSON 会话到不可变分支消息树的幂等迁移。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
import json
import math
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

import config
from core.data_loader import get_donor_display_info, to_card_donor_info
from core.preference.match_snapshot import SNAPSHOT_DONOR_KEYS
from db.donors_repo import row_to_match_dict
from dialogue.state_schema import dump_state, empty_state


@dataclass
class MigrationReport:
    scanned: int = 0
    migrated: int = 0
    would_migrate: int = 0
    skipped: int = 0
    partial: int = 0
    failed: int = 0
    verified: int = 0
    legacy_backfills: int = 0
    missing_match_runs: int = 0
    missing_donors: int = 0
    unassociated_traces: int = 0
    last_chat_id: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    trace_policy: str = "local_json_trace_ignored"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def legacy_branch_id(chat_id: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"jzk:legacy-chat:{chat_id}:root-branch")


def legacy_message_id(chat_id: int, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"jzk:legacy-chat:{chat_id}:message:{index}")


def _json(value: Any, expected: type, warnings: list[str], field_name: str):
    if isinstance(value, expected):
        return value
    try:
        loaded = json.loads(value or ("[]" if expected is list else "{}"))
    except (TypeError, ValueError):
        warnings.append(f"{field_name}:invalid_json")
        return expected()
    if not isinstance(loaded, expected):
        warnings.append(f"{field_name}:wrong_type")
        return expected()
    return loaded


def normalize_legacy_messages(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    raw = _json(value, list, warnings, "messages_json")
    messages = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            warnings.append(f"message:{index}:not_object")
            item = {"role": "system", "content": str(item)}
        role_raw = str(item.get("role") or "system").lower()
        role = "assistant" if role_raw in {"bot", "assistant", "ai"} else role_raw
        if role not in {"user", "assistant", "system"}:
            warnings.append(f"message:{index}:unknown_role:{role_raw}")
            role = "system"
        content = str(item.get("content") or "")
        if len(content) > config.CHAT_MESSAGE_MAX_CHARS:
            warnings.append(f"message:{index}:content_truncated")
            content = content[: config.CHAT_MESSAGE_MAX_CHARS]
        messages.append({**item, "role": role, "content": content})
    return messages, warnings


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def normalize_legacy_state(value: Any, latest_match_run_id: UUID | None) -> tuple[dict[str, Any], bool, list[str]]:
    warnings: list[str] = []
    raw = _json(value, dict, warnings, "state_json")
    constraints_raw = raw.get("constraints") if isinstance(raw.get("constraints"), dict) else {}
    constraints = {
        str(key): str(item)
        for key, item in constraints_raw.items()
        if str(item) in {"must", "prefer"}
    }
    if len(constraints) != len(constraints_raw):
        warnings.append("state_json:invalid_constraints_removed")
    dialogue_state = str(raw.get("dialogue_state") or raw.get("state") or "collecting")
    payload = {
        "state_schema_version": 1,
        "parsed_features": raw.get("parsed_features") if isinstance(raw.get("parsed_features"), dict) else {},
        "constraints": constraints,
        "dialogue_state": dialogue_state,
        "pending_relaxations": raw.get("pending_relaxations") if isinstance(raw.get("pending_relaxations"), list) else [],
        "preference_profile": raw.get("preference_profile") if isinstance(raw.get("preference_profile"), dict) else None,
        "latest_match_run_id": str(latest_match_run_id) if latest_match_run_id else None,
    }
    try:
        return dump_state(payload), True, warnings
    except ValueError:
        warnings.append("state_json:not_recoverable")
        return empty_state(), False, warnings


def _candidate_info(candidate: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(candidate, dict):
        return {}, {}
    donor = candidate.get("donor_info") if isinstance(candidate.get("donor_info"), dict) else {}
    explanation = {
        "reason": str(candidate.get("reason") or "历史排名回填"),
        "match_pct": candidate.get("match_pct"),
        "match_level": str(candidate.get("match_level") or "legacy_backfill"),
        "field_match": candidate.get("field_match") if isinstance(candidate.get("field_match"), dict) else {},
        "field_scores": candidate.get("field_scores") if isinstance(candidate.get("field_scores"), list) else [],
    }
    return donor, explanation


def _snapshot_from_donor_row(row: dict[str, Any]) -> dict[str, Any]:
    return to_card_donor_info(get_donor_display_info(row_to_match_dict(row)))


def _items_match_legacy_arrays(
    items: list[dict[str, Any]],
    donor_ids: list[Any],
    scores: list[Any],
) -> bool:
    return len(items) == len(donor_ids) == len(scores) and all(
        int(item["rank"]) == rank
        and int(item["donor_id"]) == int(donor_ids[rank - 1])
        and math.isclose(
            float(item["score"]),
            float(scores[rank - 1]),
            rel_tol=1e-6,
            abs_tol=1e-6,
        )
        for rank, item in enumerate(items, 1)
    )


def backfill_legacy_match_run(
    conn,
    match_run_id: UUID,
    user_id: int,
    legacy_candidates: list[Any],
    report: MigrationReport,
) -> bool:
    run = conn.execute(
        """
        SELECT id, user_id, total, donor_ids, scores, status
        FROM app.match_runs WHERE id = %s FOR UPDATE
        """,
        (match_run_id,),
    ).fetchone()
    if not run or int(run["user_id"]) != user_id:
        report.missing_match_runs += 1
        return False
    total = int(run["total"])
    donor_ids = list(run.get("donor_ids") or [])
    scores = list(run.get("scores") or [])
    if len(donor_ids) != total or len(scores) != total:
        report.missing_match_runs += 1
        return False
    existing_items = conn.execute(
        """
        SELECT rank, donor_id, score FROM app.match_run_items
        WHERE match_run_id = %s ORDER BY rank
        """,
        (match_run_id,),
    ).fetchall()
    if run["status"] == "ready":
        return _items_match_legacy_arrays(existing_items, donor_ids, scores)

    donor_rows = conn.execute(
        "SELECT * FROM donor.donors WHERE id = ANY(%s)",
        (donor_ids,),
    ).fetchall() if donor_ids else []
    donors = {int(row["id"]): row for row in donor_rows}
    for rank, (donor_id_raw, score_raw) in enumerate(zip(donor_ids, scores), 1):
        donor_id = int(donor_id_raw)
        score = float(score_raw)
        if not math.isfinite(score):
            return False
        legacy_donor, explanation = _candidate_info(
            legacy_candidates[rank - 1] if rank <= len(legacy_candidates) else None
        )
        donor_row = donors.get(donor_id)
        if donor_row:
            snapshot = _snapshot_from_donor_row(donor_row)
        else:
            report.missing_donors += 1
            snapshot = {
                key: value for key, value in legacy_donor.items() if key in SNAPSHOT_DONOR_KEYS
            }
            snapshot["code"] = str(snapshot.get("code") or f"legacy-deleted-{donor_id}")
        code = str(snapshot.get("code") or f"legacy-{donor_id}")
        conn.execute(
            """
            INSERT INTO app.match_run_items (
                match_run_id, rank, donor_id, score, donor_code_snapshot,
                donor_snapshot_json, match_explanation_json, snapshot_schema_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            ON CONFLICT (match_run_id, rank) DO NOTHING
            """,
            (match_run_id, rank, donor_id, score, code, Jsonb(snapshot), Jsonb(explanation)),
        )
    verified = conn.execute(
        """
        SELECT rank, donor_id, score
        FROM app.match_run_items WHERE match_run_id = %s
        ORDER BY rank
        """,
        (match_run_id,),
    ).fetchall()
    if not _items_match_legacy_arrays(verified, donor_ids, scores):
        return False
    conn.execute(
        """
        UPDATE app.match_runs
        SET status = 'ready', snapshot_source = 'legacy_backfill',
            snapshot_schema_version = 1, ready_at = COALESCE(ready_at, now())
        WHERE id = %s
        """,
        (match_run_id,),
    )
    report.legacy_backfills += 1
    return True


def migrate_legacy_chat(conn, row: dict[str, Any], report: MigrationReport, *, dry_run: bool = False) -> list[str]:
    chat_id = int(row["id"])
    user_id = int(row["user_id"])
    messages, warnings = normalize_legacy_messages(row.get("messages_json"))
    candidates = _json(row.get("candidates_json"), list, warnings, "candidates_json")
    legacy_state = _json(row.get("state_json"), dict, warnings, "state_json")
    if dry_run:
        _state, _recoverable, state_warnings = normalize_legacy_state(
            legacy_state,
            _uuid(legacy_state.get("match_result_id") or legacy_state.get("latest_match_run_id")),
        )
        warnings.extend(state_warnings)
        return warnings

    locked = conn.execute(
        "SELECT * FROM app.chats WHERE id = %s FOR UPDATE",
        (chat_id,),
    ).fetchone()
    if not locked or int(locked.get("storage_version") or 1) == 2:
        report.skipped += 1
        return warnings

    branch_id = legacy_branch_id(chat_id)
    conn.execute(
        """
        INSERT INTO app.chat_branches (
            id, chat_id, name, system_name, fork_reason, head_message_id,
            created_by, created_at, updated_at
        ) VALUES (%s, %s, '主分支', '迁移的主分支', 'root', NULL, 'system', %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (branch_id, chat_id, row["created_at"], row["updated_at"]),
    )

    match_occurrences: dict[UUID, int] = {}
    for index, message in enumerate(messages):
        match_id = _uuid(message.get("match_result_id"))
        if match_id:
            match_occurrences[match_id] = index
    state_match_id = _uuid(
        legacy_state.get("match_result_id") or legacy_state.get("latest_match_run_id")
    )
    if state_match_id and state_match_id not in match_occurrences:
        last_assistant = next(
            (index for index in range(len(messages) - 1, -1, -1)
             if messages[index]["role"] == "assistant"),
            None,
        )
        if last_assistant is not None:
            occupied = next(
                (candidate_id for candidate_id, message_index in match_occurrences.items()
                 if message_index == last_assistant),
                None,
            )
            if occupied is None:
                match_occurrences[state_match_id] = last_assistant
                warnings.append(f"match_run:{state_match_id}:linked_to_last_assistant")
            else:
                warnings.append(
                    f"match_run:{state_match_id}:state_reference_conflicts_with:{occupied}"
                )
        else:
            warnings.append(f"match_run:{state_match_id}:no_assistant_message_to_link")
    ready_matches: set[UUID] = set()
    for match_id in match_occurrences:
        if backfill_legacy_match_run(conn, match_id, user_id, candidates, report):
            ready_matches.add(match_id)
        else:
            warnings.append(f"match_run:{match_id}:unavailable")

    latest_match = next((match_id for match_id, index in sorted(match_occurrences.items(), key=lambda item: item[1], reverse=True) if match_id in ready_matches), None)
    final_state, final_recoverable, state_warnings = normalize_legacy_state(row.get("state_json"), latest_match)
    warnings.extend(state_warnings)
    parent_id: UUID | None = None
    created_at = row["created_at"]
    for index, message in enumerate(messages):
        message_id = legacy_message_id(chat_id, index)
        is_last = index == len(messages) - 1
        match_id = _uuid(message.get("match_result_id"))
        linked_match = (
            match_id
            if match_id in ready_matches and match_occurrences[match_id] == index
            else next(
                (candidate_id for candidate_id, message_index in match_occurrences.items()
                 if message_index == index and candidate_id in ready_matches),
                None,
            )
        )
        if match_id and linked_match is None and match_occurrences.get(match_id) != index:
            warnings.append(f"message:{index}:duplicate_match_reference")
        conn.execute(
            """
            INSERT INTO app.chat_messages (
                id, chat_id, created_in_branch_id, parent_message_id, role, status,
                content, state_schema_version, state_after_json, state_recoverable,
                match_run_id, depth, created_at, completed_at
            ) VALUES (%s, %s, %s, %s, %s, 'completed', %s, 1, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                message_id, chat_id, branch_id, parent_id, message["role"], message["content"],
                Jsonb(final_state if is_last else empty_state()),
                bool(is_last and final_recoverable), linked_match, index,
                created_at + timedelta(microseconds=index),
                created_at + timedelta(microseconds=index),
            ),
        )
        parent_id = message_id
    conn.execute(
        """
        UPDATE app.chat_branches
        SET head_message_id = %s, version = 1, updated_at = %s
        WHERE chat_id = %s AND id = %s
        """,
        (parent_id, row["updated_at"], chat_id, branch_id),
    )
    conn.execute(
        """
        UPDATE app.chats
        SET active_branch_id = %s, branch_count = 1, message_count = %s,
            storage_version = 2
        WHERE id = %s AND storage_version = 1
        """,
        (branch_id, len(messages), chat_id),
    )
    return warnings


def verify_migrated_chat(conn, chat_id: int) -> list[str]:
    issues: list[str] = []
    chat = conn.execute("SELECT * FROM app.chats WHERE id = %s", (chat_id,)).fetchone()
    if not chat or int(chat.get("storage_version") or 1) != 2:
        return ["chat:not_migrated"]
    messages, parse_warnings = normalize_legacy_messages(chat.get("messages_json"))
    issues.extend(parse_warnings)
    branch = conn.execute(
        "SELECT * FROM app.chat_branches WHERE chat_id = %s AND id = %s",
        (chat_id, chat["active_branch_id"]),
    ).fetchone()
    if not branch:
        return issues + ["branch:missing"]
    rows = conn.execute(
        """
        SELECT id, parent_message_id, role, content, depth, state_recoverable,
               state_after_json, match_run_id, created_in_branch_id
        FROM app.chat_messages WHERE chat_id = %s ORDER BY depth
        """,
        (chat_id,),
    ).fetchall()
    if len(rows) != len(messages) or int(chat["message_count"]) != len(messages):
        issues.append("messages:count_mismatch")
    for index, (actual, legacy) in enumerate(zip(rows, messages)):
        expected_parent = legacy_message_id(chat_id, index - 1) if index else None
        if actual["id"] != legacy_message_id(chat_id, index) or actual["parent_message_id"] != expected_parent:
            issues.append(f"message:{index}:parent_or_id_mismatch")
        if actual["created_in_branch_id"] != branch["id"]:
            issues.append(f"message:{index}:branch_mismatch")
        if actual["depth"] != index or actual["role"] != legacy["role"] or actual["content"] != legacy["content"]:
            issues.append(f"message:{index}:content_or_role_mismatch")
        if index < len(rows) - 1 and actual["state_recoverable"]:
            issues.append(f"message:{index}:unexpected_recoverable_state")
        if actual["match_run_id"]:
            snapshot = conn.execute(
                """
                SELECT m.status, m.total, m.donor_ids, m.scores
                FROM app.match_runs m WHERE m.id = %s
                """,
                (actual["match_run_id"],),
            ).fetchone()
            items = conn.execute(
                """
                SELECT rank, donor_id, score FROM app.match_run_items
                WHERE match_run_id = %s ORDER BY rank
                """,
                (actual["match_run_id"],),
            ).fetchall()
            if (
                not snapshot
                or snapshot["status"] != "ready"
                or int(snapshot["total"]) != len(snapshot["donor_ids"])
                or not _items_match_legacy_arrays(
                    items, list(snapshot["donor_ids"]), list(snapshot["scores"])
                )
            ):
                issues.append(f"message:{index}:incomplete_match_snapshot")
    expected_head = legacy_message_id(chat_id, len(messages) - 1) if messages else None
    if branch["head_message_id"] != expected_head or int(chat["branch_count"]) != 1:
        issues.append("branch:head_or_count_mismatch")
    actual_branch_count = int(conn.execute(
        "SELECT COUNT(*) AS count FROM app.chat_branches WHERE chat_id = %s",
        (chat_id,),
    ).fetchone()["count"])
    if actual_branch_count != 1:
        issues.append("branch:actual_count_mismatch")
    if messages and rows:
        latest_match = next(
            (row["match_run_id"] for row in reversed(rows) if row["match_run_id"]),
            None,
        )
        expected_state, expected_recoverable, _warnings = normalize_legacy_state(
            chat.get("state_json"), latest_match
        )
        if (
            rows[-1]["state_after_json"] != expected_state
            or bool(rows[-1]["state_recoverable"]) != expected_recoverable
        ):
            issues.append("message:last_state_mismatch")
    return issues
