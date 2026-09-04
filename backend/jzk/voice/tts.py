"""语音合成接口（原型阶段：前端 Web Speech API 处理，此处为生产环境预留）。"""

import logging

logger = logging.getLogger(__name__)


async def synthesize_speech(text: str, voice: str = "zh-CN") -> bytes:
    """将文本转为语音音频。

    原型阶段：语音合成由前端浏览器 SpeechSynthesis API 完成，
    此接口为生产环境（讯飞/阿里云 TTS）预留。
    """
    logger.info("TTS 接口被调用（原型阶段由前端处理）")
    raise NotImplementedError(
        "原型阶段语音合成由前端 SpeechSynthesis API 处理，"
        "生产环境请接入讯飞/阿里云 TTS 服务。"
    )
