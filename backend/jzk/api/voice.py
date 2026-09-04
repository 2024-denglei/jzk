"""语音能力 API：能力探测 + 云服务预留入口。"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from jzk import config
from jzk.api.uploads import read_upload_limited
from jzk.voice.asr import transcribe_audio
from jzk.voice.tts import synthesize_speech

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.get("/capabilities")
async def capabilities():
    """告知前端：当前以浏览器 Web Speech 为主，服务端云 ASR/TTS 未启用。"""
    return {
        "browser_asr": True,
        "browser_tts": True,
        "server_asr": False,
        "server_tts": False,
        "hint": "请在 Chrome / Edge 下使用麦克风；助手回复将自动播报。",
    }


@router.post("/transcribe")
async def voice_transcribe(file: UploadFile = File(...)):
    """生产环境预留：上传音频转写。当前未接入云 ASR。"""
    content = await read_upload_limited(file, config.MAX_AUDIO_UPLOAD_BYTES)
    try:
        text = await transcribe_audio(content, format=file.filename or "wav")
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    return {"text": text}


@router.post("/synthesize")
async def voice_synthesize(body: SpeakBody):
    """生产环境预留：文本合成音频。当前未接入云 TTS。"""
    try:
        audio = await synthesize_speech(body.text)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    from fastapi.responses import Response

    return Response(content=audio, media_type="audio/mpeg")
