"""Test Agent loop dùng FakeProvider — không cần API key, không gọi mạng.

v4: Agent.chat() giờ là generator có .send() protocol. Test drive Agent
qua AgentHarness (natural way) hoặc manual .send() (khi test protocol
violation).
"""

from __future__ import annotations

from pydantic import BaseModel

from tap.agent import Agent
from tap.events import (
    AgentErrorEvent,
    AssistantTextEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from tap.harness import AgentHarness
from tap.messages import AssistantMessage, Message, ToolCall
from tap.tools.base import BaseTool, ToolResult
from tap.tools.registry import ToolRegistry


# ---------- FakeProvider ----------

class FakeProvider:
    """Provider giả — trả về scripted responses theo thứ tự."""

    def __init__(self, scripted_responses: list[AssistantMessage]):
        self._responses = list(scripted_responses)
        self.call_count = 0
        self.received_messages: list[list[Message]] = []

    def generate(self, *, system, messages, tools) -> AssistantMessage:
        self.call_count += 1
        self.received_messages.append(list(messages))
        if not self._responses:
            raise RuntimeError("FakeProvider ran out of scripted responses")
        return self._responses.pop(0)


# ---------- Fake tool ----------

class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo input"
    args_model = EchoArgs

    def _run(self, args: EchoArgs) -> ToolResult:
        return ToolResult(output=f"ECHO: {args.text}")


# ---------- Helpers ----------

def _make_agent_harness(
    responses: list[AssistantMessage],
    tools: list[BaseTool] | None = None,
) -> tuple[Agent, AgentHarness, FakeProvider]:
    provider = FakeProvider(responses)
    tools = tools or []
    registry = ToolRegistry(tools)
    agent = Agent(
        provider=provider,
        tools=tools,
        system="test",
        max_iterations=10,
    )
    harness = AgentHarness(agent=agent, tool_executor=registry.execute)
    return agent, harness, provider


def _run(harness: AgentHarness, user_input: str):
    events = list(harness.chat(user_input))
    text_events = [e for e in events if isinstance(e, AssistantTextEvent)]
    final_text = text_events[-1].text if text_events else ""
    return events, final_text


# ---------- Tests ----------

def test_agent_yields_text_when_no_tool_call() -> None:
    agent, harness, provider = _make_agent_harness([
        AssistantMessage(text="Hello!", stop_reason="end_turn"),
    ])

    events, final_text = _run(harness, "hi")

    assert final_text == "Hello!"
    assert provider.call_count == 1
    types = [e.type for e in events]
    assert types == ["loading", "assistant_text", "agent_finish"]


def test_agent_executes_tool_and_continues() -> None:
    agent, harness, provider = _make_agent_harness(
        responses=[
            AssistantMessage(
                text="Let me echo that.",
                tool_calls=(ToolCall(id="c1", name="echo", arguments={"text": "hi"}),),
                stop_reason="tool_use",
            ),
            AssistantMessage(text="Done!", stop_reason="end_turn"),
        ],
        tools=[EchoTool()],
    )

    events, final_text = _run(harness, "echo hi please")

    assert final_text == "Done!"
    assert provider.call_count == 2

    tool_starts = [e for e in events if isinstance(e, ToolCallStartEvent)]
    tool_ends = [e for e in events if isinstance(e, ToolCallEndEvent)]
    assert len(tool_starts) == 1
    assert tool_starts[0].tool_name == "echo"
    assert tool_starts[0].arguments == {"text": "hi"}
    assert len(tool_ends) == 1
    assert tool_ends[0].ok is True

    messages = agent.messages
    assert len(messages) == 4  # user, assistant, tool_result, assistant
    assert messages[0].content == "echo hi please"
    assert messages[1].tool_calls[0].name == "echo"
    assert "ECHO: hi" in messages[2].content
    assert messages[3].text == "Done!"


def test_agent_yields_intermediate_text_before_tool_call() -> None:
    _, harness, _ = _make_agent_harness(
        responses=[
            AssistantMessage(
                text="Let me check...",
                tool_calls=(ToolCall(id="c1", name="echo", arguments={"text": "x"}),),
                stop_reason="tool_use",
            ),
            AssistantMessage(text="Result: x", stop_reason="end_turn"),
        ],
        tools=[EchoTool()],
    )

    events = list(harness.chat("go"))
    types = [e.type for e in events]

    assert types == [
        "loading",
        "assistant_text",
        "tool_call_start",
        "tool_call_end",
        "loading",
        "assistant_text",
        "agent_finish",
    ]


def test_agent_handles_unknown_tool_gracefully() -> None:
    """LLM gọi tool không tồn tại -> ok=False -> LLM tự xử lý."""
    agent, harness, provider = _make_agent_harness(
        responses=[
            AssistantMessage(
                text="",
                tool_calls=(ToolCall(id="c1", name="ghost", arguments={}),),
                stop_reason="tool_use",
            ),
            AssistantMessage(text="Tool not found, sorry.", stop_reason="end_turn"),
        ],
        tools=[EchoTool()],
    )

    events, final_text = _run(harness, "use ghost tool")

    assert final_text == "Tool not found, sorry."

    tool_ends = [e for e in events if isinstance(e, ToolCallEndEvent)]
    assert len(tool_ends) == 1
    assert tool_ends[0].ok is False

    last_call_messages = provider.received_messages[-1]
    tool_results = [m for m in last_call_messages if getattr(m, "role", None) == "tool"]
    assert len(tool_results) == 1
    assert tool_results[0].ok is False


def test_agent_stops_at_max_iterations() -> None:
    infinite_calls = [
        AssistantMessage(
            tool_calls=(ToolCall(id=f"c{i}", name="echo", arguments={"text": "x"}),),
            stop_reason="tool_use",
        )
        for i in range(100)
    ]
    _, harness, provider = _make_agent_harness(infinite_calls, tools=[EchoTool()])

    events = list(harness.chat("go"))

    assert provider.call_count == 10
    error_events = [e for e in events if isinstance(e, AgentErrorEvent)]
    assert len(error_events) == 1
    assert "max_iterations" in error_events[0].message


def test_agent_provider_exception_yields_error_event() -> None:
    class BrokenProvider:
        def generate(self, **kwargs):
            raise RuntimeError("network down")

    agent = Agent(provider=BrokenProvider(), tools=[], system="test")
    harness = AgentHarness(agent=agent, tool_executor=ToolRegistry([]).execute)

    events = list(harness.chat("hi"))
    error_events = [e for e in events if isinstance(e, AgentErrorEvent)]
    assert len(error_events) == 1
    assert "network down" in error_events[0].message
    assert "Provider error" in error_events[0].message


def test_agent_reset_clears_transcript() -> None:
    agent, harness, _ = _make_agent_harness([
        AssistantMessage(text="hi", stop_reason="end_turn"),
    ])
    list(harness.chat("first"))
    assert len(agent.messages) == 2

    agent.reset()
    assert len(agent.messages) == 0


def test_agent_on_message_callback_fires_for_each_message() -> None:
    """on_message callback phải được gọi cho user + assistant + tool_result."""
    captured: list[Message] = []

    provider = FakeProvider([
        AssistantMessage(
            text="",
            tool_calls=(ToolCall(id="c1", name="echo", arguments={"text": "hi"}),),
            stop_reason="tool_use",
        ),
        AssistantMessage(text="Done", stop_reason="end_turn"),
    ])
    tools = [EchoTool()]
    registry = ToolRegistry(tools)

    agent = Agent(
        provider=provider,
        tools=tools,
        system="test",
        on_message=captured.append,
    )
    harness = AgentHarness(agent=agent, tool_executor=registry.execute)

    list(harness.chat("go"))

    # 1 user + 2 assistant + 1 tool_result = 4
    assert len(captured) == 4
    assert captured[0].role == "user"
    assert captured[1].role == "assistant"
    assert captured[2].role == "tool"
    assert captured[3].role == "assistant"


def test_agent_load_messages_does_not_trigger_callback() -> None:
    """load_messages() không được fire on_message — messages đã trong file."""
    captured: list[Message] = []

    provider = FakeProvider([])
    agent = Agent(
        provider=provider,
        tools=[],
        system="test",
        on_message=captured.append,
    )

    from tap.messages import UserMessage
    agent.load_messages([UserMessage(content="old message")])

    assert captured == []
    assert len(agent.messages) == 1
