"""Tests for AgentHarness: drive the agent generator and execute tools.

Covers two layers:
1. Real Agent + fake executor
2. Fake agent generator + real executor (unit test for Harness)

AgentHarness handles Ctrl+C while a tool is running.
"""

from __future__ import annotations

import pytest

from tap.agent import Agent
from tap.events import (
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
    """The executor must be called each time the agent yields a ToolCallStartEvent."""
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
    """If the executor raises, Harness catches it and converts it to ok=False."""
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

    # The agent sees a tool_result with ok=False
    msgs = agent.messages
    tool_result_msg = next(m for m in msgs if m.role == "tool")
    assert tool_result_msg.ok is False
    assert "boom in executor" in tool_result_msg.content


def test_harness_forwards_all_events() -> None:
    """Non-tool-call events must also be forwarded without being swallowed."""
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
    """Demo pattern: wrap the executor to add behavior (confirmation, logging).

    This is the key benefit of separating Harness from Agent: we can add
    confirmation or logging without touching the agent itself.
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

class _OneToolCallProvider:
    """Return a single assistant turn requesting exactly one tool call."""
    def generate(self, *, system, messages, tools) -> AssistantMessage:
        return AssistantMessage(
            tool_calls=(ToolCall(id="c1", name="read", arguments={"path": "x"}),),
            stop_reason="tool_use",
        )


def test_keyboard_interrupt_mid_tool_leaves_no_orphans(assert_no_orphaned_tool_calls) -> None:
    agent = Agent(provider=_OneToolCallProvider(), tools=[], system="")

    def _interrupting_executor(name: str, arguments: dict) -> ToolResult:
        raise KeyboardInterrupt

    harness = AgentHarness(agent=agent, tool_executor=_interrupting_executor)

    # Ctrl+C must still propagate — the harness repairs the transcript but does not
    # swallow the interrupt.
    with pytest.raises(KeyboardInterrupt):
        list(harness.chat("read the file"))

    # ...and the transcript remains consistent so the next turn is still valid.
    assert_no_orphaned_tool_calls(agent.messages)
