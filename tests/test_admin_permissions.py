import asyncio

import pytest
from fastapi import HTTPException

from api import admin as admin_mod
from api.admin_permissions import (
    ADMINS_VIEW,
    DONORS_VIEW,
    DONORS_WRITE,
    REQUESTS_VIEW_OWN,
    USERS_VIEW,
    has_permission,
    permissions_for_role,
    require_permission,
)


def test_regular_admin_can_view_business_data_and_request_but_not_write():
    admin = {"role": "donor_admin"}
    assert has_permission(admin, USERS_VIEW)
    assert has_permission(admin, DONORS_VIEW)
    assert has_permission(admin, REQUESTS_VIEW_OWN)
    assert not has_permission(admin, DONORS_WRITE)
    assert not has_permission(admin, ADMINS_VIEW)


def test_super_admin_has_all_permissions():
    permissions = permissions_for_role("super_admin")
    assert DONORS_WRITE in permissions
    assert ADMINS_VIEW in permissions


def test_permission_dependency_returns_403_for_regular_admin_write():
    dependency = require_permission(DONORS_WRITE)
    with pytest.raises(HTTPException) as exc:
        dependency({"id": 2, "role": "donor_admin"})
    assert exc.value.status_code == 403


def test_admin_me_returns_backend_permissions():
    data = asyncio.run(admin_mod.admin_me({
        "id": 2,
        "username": "viewer",
        "display_name": "查看员",
        "role": "donor_admin",
    }))
    assert USERS_VIEW in data["permissions"]
    assert DONORS_WRITE not in data["permissions"]
