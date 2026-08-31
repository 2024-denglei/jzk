from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError

from api import auth as auth_mod
from api.auth import LoginRequest, PhoneCodeRequest, RegisterRequest, ResetPasswordRequest, SendCodeRequest
from api.verification_codes import VerificationCodeError, VerificationCodeStore


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        if ex is not None:
            self.expiries[key] = int(ex)
        return True

    def ttl(self, key):
        return self.expiries.get(key, -2)

    def eval(self, _script, _num_keys, key, code):
        if self.values.get(key) != code:
            return 0
        del self.values[key]
        return 1


def test_verification_code_is_scoped_one_time_and_rate_limited(monkeypatch):
    fake = _FakeRedis()
    store = VerificationCodeStore(fake)
    monkeypatch.setattr("secrets.randbelow", lambda _limit: 123456)

    code, expires = store.issue("register", "+8613800138000")
    assert code == "123456"
    assert expires > 0
    assert not store.verify_and_consume("login", "+8613800138000", code)
    assert store.verify_and_consume("register", "+8613800138000", code)
    assert not store.verify_and_consume("register", "+8613800138000", code)

    try:
        store.issue("register", "+8613800138000")
        assert False, "expected cooldown error"
    except VerificationCodeError as exc:
        assert "请求过于频繁" in str(exc)


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeDatabase:
    def __init__(self):
        self.users: list[dict] = []

    @contextmanager
    def session(self):
        yield _FakeConnection(self)


class _FakeConnection:
    def __init__(self, database: _FakeDatabase):
        self.database = database

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT id FROM app.users WHERE phone"):
            user = self._find("phone", params[0])
            return _Cursor({"id": user["id"]} if user else None)
        if normalized.startswith("SELECT email, phone FROM app.users"):
            user = next(
                (item for item in self.database.users if item["email"] == params[0] or item["phone"] == params[1]),
                None,
            )
            return _Cursor({"email": user["email"], "phone": user["phone"]} if user else None)
        if normalized.startswith("INSERT INTO app.users"):
            email, phone, password_hash, nickname = params
            user = {
                "id": len(self.database.users) + 1,
                "email": email,
                "phone": phone,
                "password_hash": password_hash,
                "nickname": nickname,
                "status": "active",
                "token_version": 0,
                "last_login_at": None,
                "created_at": datetime.now(timezone.utc),
            }
            self.database.users.append(user)
            return _Cursor(user)
        if normalized.startswith("SELECT * FROM app.users WHERE email"):
            return _Cursor(self._find("email", params[0]))
        if normalized.startswith("SELECT * FROM app.users WHERE phone"):
            return _Cursor(self._find("phone", params[0]))
        if normalized.startswith("UPDATE app.users SET last_login_at"):
            user = self._find("id", params[0])
            if user:
                user["last_login_at"] = datetime.now(timezone.utc)
            return _Cursor(user)
        if normalized.startswith("UPDATE app.users SET password_hash"):
            user = self._find("id", params[1])
            if user:
                user["password_hash"] = params[0]
                user["token_version"] += 1
            return _Cursor()
        raise AssertionError(f"unexpected SQL: {normalized}")

    def _find(self, field, value):
        return next((item for item in self.database.users if item[field] == value), None)


class _FakeCodes:
    def __init__(self):
        self.codes: dict[tuple[str, str], str] = {}

    def issue(self, purpose, phone):
        self.codes[(purpose, phone)] = "654321"
        return "654321", 300

    def verify_and_consume(self, purpose, phone, code):
        key = (purpose, phone)
        if self.codes.get(key) != code:
            return False
        del self.codes[key]
        return True


def test_register_password_and_code_login_and_password_reset(monkeypatch):
    database = _FakeDatabase()
    codes = _FakeCodes()
    monkeypatch.setattr(auth_mod, "db_session", database.session)
    monkeypatch.setattr(auth_mod, "verification_codes", codes)
    monkeypatch.setattr(auth_mod.config, "EXPOSE_TEST_VERIFICATION_CODE", True)

    phone = "13800138000"

    async def scenario():
        sent = await auth_mod.send_code(SendCodeRequest(phone=phone, purpose="register"))
        assert sent["test_code"] == "654321"

        registered = await auth_mod.register(RegisterRequest(**{
            "email": "USER@example.com",
            "phone": phone,
            "password": "oldpass",
            "code": "654321",
        }))
        assert registered["user"]["email"] == "user@example.com"
        assert registered["user"]["phone"] == "+8613800138000"

        for identifier in ("user@example.com", phone):
            logged_in = await auth_mod.login(LoginRequest(identifier=identifier, password="oldpass"))
            assert logged_in["access_token"]

        await auth_mod.send_code(SendCodeRequest(phone=phone, purpose="login"))
        code_login = await auth_mod.phone_login(PhoneCodeRequest(phone=phone, code="654321"))
        assert code_login["access_token"]
        try:
            await auth_mod.phone_login(PhoneCodeRequest(phone=phone, code="654321"))
            assert False, "expected one-time code rejection"
        except HTTPException as exc:
            assert exc.status_code == 400

        await auth_mod.send_code(SendCodeRequest(phone=phone, purpose="reset_password"))
        reset = await auth_mod.reset_password(
            ResetPasswordRequest(phone=phone, code="654321", new_password="newpass")
        )
        assert reset == {"ok": True}
        try:
            await auth_mod.login(LoginRequest(identifier=phone, password="oldpass"))
            assert False, "expected old password rejection"
        except HTTPException as exc:
            assert exc.status_code == 400
        assert (await auth_mod.login(LoginRequest(identifier=phone, password="newpass")))["access_token"]

        database.users[0]["status"] = "disabled"
        try:
            await auth_mod.login(LoginRequest(identifier=phone, password="newpass"))
            assert False, "expected disabled account rejection"
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "账号已停用" in exc.detail

    asyncio.run(scenario())


def test_registration_requires_phone_and_code():
    try:
        RegisterRequest(email="user@example.com", password="secret1")
        assert False, "expected validation error"
    except ValidationError as exc:
        missing = {item["loc"][0] for item in exc.errors() if item["type"] == "missing"}
        assert missing == {"phone", "code"}
