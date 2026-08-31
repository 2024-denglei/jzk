import asyncio
from types import SimpleNamespace

from api.chat_stream import StreamChatRequest, chat_stream
from api.chat_stream import inject_dependencies as inject_stream_dependencies
from dialogue.session import SessionManager


class _GatedAsyncCompletions:
    def __init__(self, started: asyncio.Event, release: asyncio.Event):
        self.started = started
        self.release = release

    async def create(self, **_kwargs):
        self.started.set()
        await self.release.wait()
        message = SimpleNamespace(content="处理完成", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_chat_llm_wait_does_not_block_other_requests(monkeypatch):
    """LLM 仍在等待时，同一 ASGI 进程必须能继续处理分页等请求。"""

    async def scenario():
        from api import chat_stream as stream_mod

        started = asyncio.Event()
        release = asyncio.Event()
        completions = _GatedAsyncCompletions(started, release)
        llm = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        inject_stream_dependencies(SessionManager(), object(), object(), llm)
        monkeypatch.setattr(stream_mod, "_maybe_persist", lambda *_args, **_kwargs: None)

        request = SimpleNamespace(
            app=SimpleNamespace(),
            headers={},
            is_disconnected=lambda: asyncio.sleep(0, result=False),
        )
        response = await chat_stream(
            StreamChatRequest(session_id=None, message="本科以上"),
            request,
            user_id=42,
        )

        async def consume_stream():
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        chat_task = asyncio.create_task(consume_stream())
        await asyncio.wait_for(started.wait(), timeout=1)
        # 若同步 SDK 占住事件循环，这个代表分页请求的协程也无法获得执行机会。
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.2)

        release.set()
        chat_text = await asyncio.wait_for(chat_task, timeout=1)
        assert "处理完成" in chat_text

    asyncio.run(scenario())
