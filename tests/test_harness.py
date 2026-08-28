"""Test AgentHarness — drive Agent generator, execute tool.

Test 2 tầng:
1. Với real Agent + fake executor
2. Với fake Agent generator + real executor (unit test cho Harness)
"""

from __future__ import annotations

from collections.abc import Generator

from tap.agent import Agent
from tap.events import (
    AgentEvent,
    AgentFinishEvent,
    LoadingEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from tap.harness import AgentHarness
from tap.messages import AssistantMessage, ToolCall
from tap.tools.base import ToolResult


class FakeProvider:
    def __init__(self, responses):
        self._responses = list(responses)

    def generate(self, **kwargs):
        return self._responses.pop(0)


def test_harness_calls_executor_for_each_tool_call() -> None:
    """Executor phải được gọi mỗi khi Agent yield ToolCallStartEvent."""
    executor_calls = []

    def executor(name: str, args: dict) -> ToolResult:
        executor_calls.append((name, args))
        return ToolResult(output=f"result of {name}", ok=True)

    provider = FakeProvider([
        AssistantMessage(
            tool_calls=(
                ToolCall(id="c1", name="alpha", arguments={"x": 1}),
                ToolCall(id="c2", name="beta", arguments={"y": 2}),
            ),
            stop_reason="tool_use",
        ),
        AssistantMessage(text="done", stop_reason="end_turn"),
    ])
    agent = Agent(provider=provider, tools=[], system="test")
    harness = AgentHarness(agent=agent, tool_executor=executor)

    list(harness.chat("go"))

    assert executor_calls == [
        ("alpha", {"x": 1}),
        ("beta", {"y": 2}),
    ]


def test_harness_wraps_executor_exception_as_ok_false() -> None:
    """Nếu executor raise, Harness bắt và biến thành ok=False (defensive)."""
    def crashing_executor(name, args):
        raise RuntimeError("boom in executor")

    provider = FakeProvider([
        AssistantMessage(
            tool_calls=(ToolCall(id="c1", name="x", arguments={}),),
            stop_reason="tool_use",
        ),
        AssistantMessage(text="ok", stop_reason="end_turn"),
    ])
    agent = Agent(provider=provider, tools=[], system="test")
    harness = AgentHarness(agent=agent, tool_executor=crashing_executor)

    events = list(harness.chat("go"))

    tool_ends = [e for e in events if isinstance(e, ToolCallEndEvent)]
    assert len(tool_ends) == 1
    assert tool_ends[0].ok is False

    # Agent thấy tool_result với ok=False
    msgs = agent.messages
    tool_result_msg = next(m for m in msgs if m.role == "tool")
    assert tool_result_msg.ok is False
    assert "boom in executor" in tool_result_msg.content


def test_harness_forwards_all_events() -> None:
    """Events không phải tool_call_start cũng phải forward, không nuốt."""
    provider = FakeProvider([
        AssistantMessage(text="hi", stop_reason="end_turn"),
    ])
    agent = Agent(provider=provider, tools=[], system="test")
    harness = AgentHarness(
        agent=agent,
        tool_executor=lambda n, a: ToolResult(output="", ok=True),
    )

    events = list(harness.chat("hello"))
    types = [e.type for e in events]

    assert "loading" in types
    assert "assistant_text" in types
    assert "agent_finish" in types


def test_harness_can_wrap_executor_with_confirmation() -> None:
    """Demo pattern: wrap executor để thêm behavior (confirmation, logging).

    Đây là lợi ích chính của việc tách Harness khỏi Agent — không đụng
    Agent cũng thêm được confirmation.
    """
    inner_executor = lambda n, a: ToolResult(output="did it", ok=True)

    call_log = []

    def logging_executor(name: str, args: dict) -> ToolResult:
        call_log.append((name, args))
        return inner_executor(name, args)

    provider = FakeProvider([
        AssistantMessage(
            tool_calls=(ToolCall(id="c1", name="foo", arguments={"a": 1}),),
            stop_reason="tool_use",
        ),
        AssistantMessage(text="ok", stop_reason="end_turn"),
    ])
    agent = Agent(provider=provider, tools=[], system="test")
    harness = AgentHarness(agent=agent, tool_executor=logging_executor)

    list(harness.chat("go"))

    assert call_log == [("foo", {"a": 1})]
