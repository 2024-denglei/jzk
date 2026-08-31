import asyncio

import pytest
from fastapi import HTTPException

from api.uploads import read_upload_limited


class _Upload:
    def __init__(self, content: bytes):
        self.content = content
        self.position = 0

    async def read(self, size: int) -> bytes:
        chunk = self.content[self.position : self.position + size]
        self.position += len(chunk)
        return chunk


def test_upload_under_limit_is_returned():
    result = asyncio.run(read_upload_limited(_Upload(b"abc"), 3))
    assert result == b"abc"


def test_upload_over_limit_returns_413():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload_limited(_Upload(b"abcd"), 3))
    assert exc.value.status_code == 413
