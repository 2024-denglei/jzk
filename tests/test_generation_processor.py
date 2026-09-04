import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from jzk.advisor import generation_processor
from jzk.advisor.agent_tools import AGENT_SYSTEM_PROMPT, PREFERENCE_SNAPSHOT_PREFIX
from jzk.advisor.generation_processor import AgentGenerationProcessor, FallbackGenerationProcessor


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


def _context(*, preference_profile=None):
    generation = SimpleNamespace(
        user_id=7,
        assistant_message_id=uuid4(),
    )
    state = {"state_schema_version": 1}
    if preference_profile is not None:
        state["preference_profile"] = preference_profile
    return {
        "generation": generation,
        "messages": [
            {"id": str(uuid4()), "role": "user", "content": "必须 O 型"},
        ],
        "state_after_user": state,
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
    captured = {}

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
            if not kwargs.get("stream"):
                captured["tools"] = kwargs.get("tools")
                captured["messages"] = kwargs.get("messages")
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
    existing = {
        "schema_version": "1.0",
        "attributes": {
            "education": {"constraint": "must", "weight": 1, "values": ["本科"]},
        },
    }
    output = asyncio.run(
        AgentGenerationProcessor(client)(
            _context(preference_profile=existing),
            control,
        )
    )

    assert output.content == "匹配完成"
    assert output.match_run_id == UUID(result_set_id)
    assert control.state["latest_match_run_id"] == result_set_id
    assert [event for event, _payload in control.events] == [
        "agent_stage", "agent_stage", "match_ready", "agent_stage",
    ]
    assert control.events[0][1]["stage"] == "thinking"
    assert control.events[1][1] == {
        "stage": "tool_call", "tool_name": "submit_preference_profile",
    }
    assert control.events[2][1]["total"] == 12
    assert control.events[3][1]["stage"] == "summarizing"
    assert control.metadata["prompt_version"] == "agent-v4"
    assert all("content" not in payload for _step, payload in control.trace.steps)
    assert len(captured["tools"]) == 1
    assert captured["tools"][0]["function"]["name"] == "submit_preference_profile"
    assert captured["messages"][0]["content"] == AGENT_SYSTEM_PROMPT
    assert captured["messages"][1]["content"].startswith(PREFERENCE_SNAPSHOT_PREFIX)
    assert "本科" in captured["messages"][1]["content"]
    transcript = [payload for step, payload in control.trace.steps if step == "agent_message"]
    assert [item["role"] for item in transcript] == [
        "system", "system", "user", "assistant", "tool", "assistant",
    ]
    assert transcript[0]["text"] == AGENT_SYSTEM_PROMPT
    assert transcript[1]["kind"] == "preference_snapshot"
    assert transcript[1]["text"].startswith(PREFERENCE_SNAPSHOT_PREFIX)
    assert transcript[2]["text"] == "必须 O 型"
    assert transcript[3]["phase"] == "tool_call"
    assert transcript[3]["tool_calls"][0]["name"] == "submit_preference_profile"
    assert json.loads(transcript[4]["text"])["result_set_id"] == result_set_id
    assert transcript[5]["phase"] == "final"
    assert transcript[5]["text"] == "匹配完成"


def test_agent_processor_accepts_extended_tool(monkeypatch):
    result_set_id = str(uuid4())
    tool_call = SimpleNamespace(
        id="call-ext",
        function=SimpleNamespace(
            name="submit_preference_profile_extended",
            arguments=json.dumps(
                {
                    "schema_version": "1.0",
                    "attributes": {
                        "smoke_history": {
                            "constraint": "must",
                            "weight": 1,
                            "keywords": ["无"],
                            "match": "any",
                        }
                    },
                }
            ),
        ),
    )
    tool_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))]
    )
    captured = {}

    async def stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="好的"))])

    class Completions:
        async def create(self, **kwargs):
            if not kwargs.get("stream"):
                captured["tools"] = kwargs.get("tools")
            return stream() if kwargs.get("stream") else tool_response

    monkeypatch.setattr(
        generation_processor,
        "execute_match",
        lambda *_args, **_kwargs: {
            "ok": True,
            "total": 3,
            "filtered_count": 3,
            "match_level": "full",
            "prefer_hits": [],
            "bottlenecks": [],
            "result_set_id": result_set_id,
        },
    )
    control = _Control()
    ctx = _context()
    ctx["messages"] = [{"id": str(uuid4()), "role": "user", "content": "不要抽烟的"}]
    output = asyncio.run(
        AgentGenerationProcessor(
            SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        )(ctx, control)
    )
    assert captured["tools"][0]["function"]["name"] == (
        "submit_preference_profile_extended"
    )
    assert output.match_run_id == UUID(result_set_id)
    assert control.state["preference_profile"]["attributes"]["smoke_history"]["keywords"] == ["无"]


def test_agent_processor_returns_structured_validation_error(monkeypatch):
    bad_call = SimpleNamespace(
        id="call-bad",
        function=SimpleNamespace(
            name="submit_preference_profile",
            arguments=json.dumps(
                {
                    "schema_version": "1.0",
                    "attributes": {
                        "figure": {
                            "constraint": "must",
                            "weight": 1,
                            "values": ["偏瘦型"],
                        }
                    },
                }
            ),
        ),
    )
    good_call = SimpleNamespace(
        id="call-good",
        function=SimpleNamespace(
            name="submit_preference_profile",
            arguments=json.dumps(
                {
                    "schema_version": "1.0",
                    "attributes": {
                        "figure": {
                            "constraint": "must",
                            "weight": 1,
                            "values": ["瘦弱"],
                        }
                    },
                }
            ),
        ),
    )
    responses = [
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[bad_call]))]
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[good_call]))]
        ),
    ]

    async def stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="已修正"))])

    class Completions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            if kwargs.get("stream"):
                return stream()
            response = responses[self.calls]
            self.calls += 1
            return response

    monkeypatch.setattr(
        generation_processor,
        "execute_match",
        lambda profile, **_kwargs: {
            "ok": True,
            "total": 1,
            "filtered_count": 1,
            "match_level": "full",
            "prefer_hits": [],
            "bottlenecks": [],
            "result_set_id": str(uuid4()),
        },
    )
    control = _Control()
    output = asyncio.run(
        AgentGenerationProcessor(
            SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        )(_context(), control)
    )
    tool_msgs = [
        payload
        for step, payload in control.trace.steps
        if step == "agent_message" and payload.get("phase") == "tool_result"
    ]
    assert len(tool_msgs) == 2
    first = json.loads(tool_msgs[0]["text"])
    assert first["ok"] is False
    assert first["field"] == "figure"
    assert first["allowed_values"] == ["一般", "瘦弱", "强壮", "肥胖"]
    assert json.loads(tool_msgs[1]["text"])["ok"] is True
    assert output.content == "已修正"
