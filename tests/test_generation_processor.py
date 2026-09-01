import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from dialogue import generation_processor
from dialogue.generation_processor import AgentGenerationProcessor, FallbackGenerationProcessor


class _Trace:
    def __init__(self):
        self.steps = []

    def add(self, step, **payload):
        self.steps.append((step, payload))


class _Control:
    def __init__(self):
        self.trace = _Trace()
        self.tokens = []
        self.events = []
        self.state = None

    async def cancelled(self):
        return False

    async def set_state(self, state):
        self.state = state

    async def emit_token(self, text):
        self.tokens.append(text)

    async def emit_event(self, event, payload):
        self.events.append((event, payload))

    async def set_model_metadata(self, **metadata):
        self.metadata = metadata

    async def checkpoint(self):
        return False


def _context():
    generation = SimpleNamespace(
        user_id=7,
        assistant_message_id=uuid4(),
    )
    return {
        "generation": generation,
        "messages": [
            {"id": str(uuid4()), "role": "user", "content": "必须 O 型"},
        ],
        "state_after_user": {"state_schema_version": 1},
    }


def test_fallback_processor_does_not_invent_match_counts():
    control = _Control()
    output = asyncio.run(FallbackGenerationProcessor()(_context(), control))
    assert "未配置" in output.content
    assert not output.match_run_id
    assert control.tokens == [output.content]
    assert control.metadata["model"] == "fallback"


def test_agent_processor_creates_match_snapshot_ref_and_streams_summary(monkeypatch):
    result_set_id = str(uuid4())
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="submit_preference_profile",
            arguments=json.dumps(
                {
                    "schema_version": "1.0",
                    "attributes": {
                        "abo_blood": {
                            "constraint": "must",
                            "weight": 1,
                            "values": ["O"],
                        }
                    },
                }
            ),
        ),
    )
    tool_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))]
    )

    async def stream():
        for text in ("匹配", "完成"):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
            )

    class Completions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            return stream() if kwargs.get("stream") else tool_response

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(
        generation_processor,
        "execute_match",
        lambda *_args, **_kwargs: {
            "ok": True,
            "total": 12,
            "match_level": "full",
            "prefer_hits": [],
            "bottlenecks": [],
            "result_set_id": result_set_id,
        },
    )
    control = _Control()
    output = asyncio.run(AgentGenerationProcessor(client)(_context(), control))

    assert output.content == "匹配完成"
    assert output.match_run_id == UUID(result_set_id)
    assert control.state["latest_match_run_id"] == result_set_id
    assert control.events[0][0] == "match_ready"
    assert control.events[0][1]["total"] == 12
    assert control.metadata["prompt_version"] == "agent-v2"
    assert all("content" not in payload for _step, payload in control.trace.steps)
    transcript = [payload for step, payload in control.trace.steps if step == "agent_message"]
    assert [item["role"] for item in transcript] == [
        "system", "user", "assistant", "tool", "assistant",
    ]
    assert transcript[0]["text"] == generation_processor.AGENT_SYSTEM_PROMPT
    assert transcript[1]["text"] == "必须 O 型"
    assert transcript[2]["phase"] == "tool_call"
    assert transcript[2]["tool_calls"][0]["name"] == "submit_preference_profile"
    assert json.loads(transcript[3]["text"])["result_set_id"] == result_set_id
    assert transcript[4]["phase"] == "final"
    assert transcript[4]["text"] == "匹配完成"
