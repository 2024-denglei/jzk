"""管理端角色与细粒度权限。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException

from jzk.api.admin_auth import get_current_admin

DASHBOARD_VIEW = "dashboard:view"
USERS_VIEW = "users:view"
USERS_CONTROL = "users:control"
USERS_CONTROL_REQUEST = "users:control_request"
DONORS_VIEW = "donors:view"
DONORS_WRITE = "donors:write"
DONORS_WRITE_REQUEST = "donors:write_request"
DONORS_IMPORT = "donors:import"
DONORS_AUDIT_VIEW = "donors:audit:view"
REQUESTS_VIEW_OWN = "requests:view_own"
REQUESTS_REVIEW = "requests:review"
ADMINS_VIEW = "admins:view"
ADMINS_MANAGE = "admins:manage"
SYSTEM_CACHE_REFRESH = "system:cache_refresh"

ALL_PERMISSIONS = frozenset({
    DASHBOARD_VIEW,
    USERS_VIEW,
    USERS_CONTROL,
    USERS_CONTROL_REQUEST,
    DONORS_VIEW,
    DONORS_WRITE,
    DONORS_WRITE_REQUEST,
    DONORS_IMPORT,
    DONORS_AUDIT_VIEW,
    REQUESTS_VIEW_OWN,
    REQUESTS_REVIEW,
    ADMINS_VIEW,
    ADMINS_MANAGE,
    SYSTEM_CACHE_REFRESH,
})

ROLE_PERMISSIONS = {
    "super_admin": ALL_PERMISSIONS,
    "donor_admin": frozenset({
        DASHBOARD_VIEW,
        USERS_VIEW,
        USERS_CONTROL_REQUEST,
        DONORS_VIEW,
        DONORS_WRITE_REQUEST,
        DONORS_AUDIT_VIEW,
        REQUESTS_VIEW_OWN,
    }),
}


def permissions_for_role(role: str | None) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role or "", frozenset()))


def has_permission(admin: dict, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(str(admin.get("role") or ""), frozenset())


def require_permission(permission: str) -> Callable:
    def dependency(admin: dict = Depends(get_current_admin)) -> dict:
        if not has_permission(admin, permission):
            raise HTTPException(status_code=403, detail="无权访问或执行该操作")
        return admin

    return dependency
