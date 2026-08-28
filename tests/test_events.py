"""Test event types — frozen + discriminator field."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tap.events import (
    AgentErrorEvent,
    AgentFinishEvent,
    AssistantTextEvent,
    LoadingEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)


def test_events_have_type_discriminator() -> None:
    """Mỗi event có field `type` để match trong CLI."""
    assert LoadingEvent().type == "loading"
    assert AssistantTextEvent(text="x").type == "assistant_text"
    assert ToolCallStartEvent(tool_name="t", arguments={}).type == "tool_call_start"
    assert ToolCallEndEvent(tool_name="t", ok=True).type == "tool_call_end"
    assert AgentFinishEvent().type == "agent_finish"
    assert AgentErrorEvent(message="x").type == "agent_error"


def test_events_are_frozen() -> None:
    """Events phải immutable — không được sửa sau khi tạo."""
    ev = AssistantTextEvent(text="hi")
    with pytest.raises(ValidationError):
        ev.text = "changed"


def test_tool_call_start_stores_arguments() -> None:
    ev = ToolCallStartEvent(
        tool_name="read",
        arguments={"path": "foo.txt"},
    )
    assert ev.tool_name == "read"
    assert ev.arguments == {"path": "foo.txt"}


def test_tool_call_end_ok_flag() -> None:
    ok_event = ToolCallEndEvent(tool_name="read", ok=True)
    fail_event = ToolCallEndEvent(tool_name="read", ok=False)
    assert ok_event.ok is True
    assert fail_event.ok is False
