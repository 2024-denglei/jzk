"""上传文件的流式体积限制。"""

from fastapi import HTTPException, UploadFile

_READ_CHUNK_BYTES = 1024 * 1024


async def read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """分块读取上传内容，超过限制立即终止，避免一次性无界读入内存。"""
    content = bytearray()
    while True:
        remaining = max_bytes - len(content)
        chunk = await file.read(min(_READ_CHUNK_BYTES, remaining + 1))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="上传文件过大")
