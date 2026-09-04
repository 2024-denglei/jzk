"""语音识别接口（原型阶段：前端 Web Speech API 处理，此处为生产环境预留）。"""

import logging

logger = logging.getLogger(__name__)


async def transcribe_audio(audio_bytes: bytes, format: str = "wav") -> str:
    """将音频转为文本。

    原型阶段：语音识别由前端浏览器 Web Speech API 完成，
    此接口为生产环境（讯飞/阿里云 ASR）预留。
    """
    logger.info("ASR 接口被调用（原型阶段由前端处理）")
    raise NotImplementedError(
        "原型阶段语音识别由前端 Web Speech API 处理，"
        "生产环境请接入讯飞/阿里云 ASR 服务。"
    )
