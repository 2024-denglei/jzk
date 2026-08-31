import pytest
from fastapi import HTTPException, Request

from api.security import validate_cookie_origin


def _request(origin: str | None, host: str = "api.example.com") -> Request:
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/api/auth/refresh",
            "query_string": b"",
            "headers": headers,
            "server": (host, 443),
        }
    )


def test_same_origin_cookie_request_is_allowed():
    validate_cookie_origin(_request("https://api.example.com"))


def test_non_browser_client_without_origin_is_allowed():
    validate_cookie_origin(_request(None))


def test_untrusted_cookie_origin_is_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_cookie_origin(_request("https://attacker.example"))
    assert exc.value.status_code == 403
