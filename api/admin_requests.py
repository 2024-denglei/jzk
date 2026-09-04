"""普通管理员操作申请与超级管理员审批 API。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from api.admin import DonorUpsertBody
from api.admin_permissions import (
    DONORS_WRITE_REQUEST,
    REQUESTS_REVIEW,
    REQUESTS_VIEW_OWN,
    USERS_CONTROL_REQUEST,
    has_permission,
    require_permission,
)
from matching.runtime_cache import refresh_donor_cache, update_donor_status_cache
from db.admin_requests_repo import (
    cancel_operation_request,
    claim_operation_request,
    complete_operation_request,
    create_operation_request,
    list_operation_requests,
    reject_operation_request,
)
from db.admin_users_repo import control_user, get_user_profile
from db.donors_repo import get_donor_by_code, set_donor_status, upsert_donor

router = APIRouter(prefix="/api/admin/requests", tags=["admin-requests"])

Action = Literal[
    "donor_create",
    "donor_update",
    "donor_status",
    "user_kick",
    "user_disable",
    "user_enable",
]

DONOR_ACTIONS = {"donor_create", "donor_update", "donor_status"}
USER_ACTIONS = {"user_kick", "user_disable", "user_enable"}
VALID_STATUSES = {"pending", "processing", "approved", "rejected", "cancelled", "failed"}


class OperationRequestBody(BaseModel):
    action: Action
    target_id: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=2, max_length=500)


class ReviewBody(BaseModel):
    comment: str = Field(default="", max_length=500)


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _validated_payload(body: OperationRequestBody) -> dict[str, Any]:
    if body.action in {"donor_create", "donor_update"}:
        try:
            payload = DonorUpsertBody.model_validate(body.payload).model_dump()
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=f"档案数据无效：{exc.errors()[0]['msg']}")
        payload["code"] = body.target_id.strip()
        return payload
    if body.action == "donor_status":
        status = body.payload.get("status")
        if status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail="档案状态必须为 active 或 disabled")
        return {"status": status}
    return {}


def _snapshot_for(body: OperationRequestBody, payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    target_id = body.target_id.strip()
    if body.action in DONOR_ACTIONS:
        current = get_donor_by_code(target_id)
        if body.action == "donor_create":
            if current:
                raise HTTPException(status_code=409, detail="该捐精人档案已存在")
            code = str(payload.get("code") or "").strip()
            if not code or code != target_id:
                raise HTTPException(status_code=400, detail="新建档案的代号与目标标识不一致")
        elif not current:
            raise HTTPException(status_code=404, detail="捐精人档案不存在")
        return "donor", current

    try:
        user_id = int(target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="用户 ID 格式错误")
    current = get_user_profile(user_id)
    if not current:
        raise HTTPException(status_code=404, detail="用户不存在")
    return "user", {
        "id": current["id"],
        "status": current.get("status"),
        "updated_at": current.get("updated_at"),
    }


def _assert_target_unchanged(item: dict[str, Any]) -> None:
    before = item.get("before_snapshot") or {}
    if item["target_type"] == "donor":
        current = get_donor_by_code(str(item["target_id"]))
        if item["action"] == "donor_create":
            if current:
                raise ValueError("目标档案已被创建，请重新提交申请")
            return
    else:
        current = get_user_profile(int(item["target_id"]))
    if not current:
        raise ValueError("目标对象已不存在")
    current_version = _serialize(current.get("updated_at"))
    before_version = _serialize(before.get("updated_at"))
    if current_version != before_version:
        raise ValueError("目标数据在申请后已发生变化，请重新提交申请")


def _execute(item: dict[str, Any], reviewer_id: int, request: Request) -> None:
    _assert_target_unchanged(item)
    action = item["action"]
    payload = dict(item.get("payload") or {})
    target_id = str(item["target_id"])
    expected_updated_at = _serialize((item.get("before_snapshot") or {}).get("updated_at"))
    if action == "donor_create":
        upsert_donor(payload, operator_id=reviewer_id, action="create", must_create=True)
        refresh_donor_cache(request.app)
    elif action == "donor_update":
        payload["code"] = target_id
        upsert_donor(payload, operator_id=reviewer_id, action="update", expected_updated_at=expected_updated_at)
        refresh_donor_cache(request.app)
    elif action == "donor_status":
        status = str(payload.get("status") or "")
        set_donor_status(target_id, status, reviewer_id, expected_updated_at=expected_updated_at)
        if not update_donor_status_cache(request.app, target_id, status):
            refresh_donor_cache(request.app)
    elif action in USER_ACTIONS:
        control_user(
            int(target_id),
            action.removeprefix("user_"),
            reviewer_id,
            f"审批申请 #{item['id']}：{item['reason']}",
            expected_updated_at=expected_updated_at,
        )
    else:
        raise ValueError("不支持的申请操作")


@router.post("")
async def submit_operation_request(
    body: OperationRequestBody,
    admin: dict = Depends(require_permission(REQUESTS_VIEW_OWN)),
):
    needed = DONORS_WRITE_REQUEST if body.action in DONOR_ACTIONS else USERS_CONTROL_REQUEST
    if not has_permission(admin, needed):
        raise HTTPException(status_code=403, detail="无权提交该类型的操作申请")
    reason = body.reason.strip()
    if len(reason) < 2:
        raise HTTPException(status_code=400, detail="申请理由至少需要 2 个字")
    if not body.target_id.strip():
        raise HTTPException(status_code=400, detail="目标标识不能为空")
    payload = _validated_payload(body)
    target_type, snapshot = _snapshot_for(body, payload)
    row = create_operation_request(
        requester_id=int(admin["id"]),
        action=body.action,
        target_type=target_type,
        target_id=body.target_id.strip(),
        payload=payload,
        before_snapshot=snapshot,
        reason=reason,
    )
    return _serialize(row)


@router.get("/mine")
async def my_operation_requests(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(require_permission(REQUESTS_VIEW_OWN)),
):
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="申请状态无效")
    rows, total, page, page_size = list_operation_requests(
        requester_id=int(admin["id"]), status=status, page=page, page_size=page_size
    )
    return {"items": _serialize(rows), "total": total, "page": page, "page_size": page_size}


@router.post("/{request_id}/cancel")
async def cancel_my_operation_request(
    request_id: int,
    admin: dict = Depends(require_permission(REQUESTS_VIEW_OWN)),
):
    row = cancel_operation_request(request_id, int(admin["id"]))
    if not row:
        raise HTTPException(status_code=409, detail="申请不存在、已处理或不属于当前管理员")
    return _serialize(row)


@router.get("")
async def review_operation_requests(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(require_permission(REQUESTS_REVIEW)),
):
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="申请状态无效")
    rows, total, page, page_size = list_operation_requests(status=status, page=page, page_size=page_size)
    return {"items": _serialize(rows), "total": total, "page": page, "page_size": page_size}


@router.post("/{request_id}/approve")
async def approve_operation_request(
    request_id: int,
    body: ReviewBody,
    request: Request,
    admin: dict = Depends(require_permission(REQUESTS_REVIEW)),
):
    item = claim_operation_request(request_id, int(admin["id"]))
    if not item:
        raise HTTPException(status_code=409, detail="申请不存在、已处理或不能审批自己的申请")
    try:
        _execute(item, int(admin["id"]), request)
    except Exception as exc:
        complete_operation_request(request_id, status="failed", review_comment=body.comment, execution_error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    row = complete_operation_request(request_id, status="approved", review_comment=body.comment)
    return _serialize(row)


@router.post("/{request_id}/reject")
async def reject_pending_operation_request(
    request_id: int,
    body: ReviewBody,
    admin: dict = Depends(require_permission(REQUESTS_REVIEW)),
):
    if len(body.comment.strip()) < 2:
        raise HTTPException(status_code=400, detail="驳回时请填写原因")
    row = reject_operation_request(request_id, int(admin["id"]), body.comment.strip())
    if not row:
        raise HTTPException(status_code=409, detail="申请不存在、已处理或不能审批自己的申请")
    return _serialize(row)
