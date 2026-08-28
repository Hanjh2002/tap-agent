"""Agent events — streamed out for the CLI (or another frontend) to render.

Event system olves a problem: in v1, Agent.chat() stayed silent until it
was completely done. v2 yields events step by step so the user sees progress.

Each event is a frozen pydantic model with a `type` field (a string literal)
used to discriminate in pattern matching.

Extensible: adding a new event (e.g. TextDeltaEvent for streaming) only
requires a new class + union entry, without touching the existing interface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class LoadingEvent(BaseModel):
    """Agentis starting a provider call — awaiting the response."""
    model_config = ConfigDict(frozen=True)

    type: Literal["loading"] = "loading"


class AssistantTextEvent(BaseModel):
    """Assistant returned text (may be intermediate before a tool call,
    or the final answer)."""
    model_config = ConfigDict(frozen=True)

    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ThoughtEvent(BaseModel):
    """A summary of the model's reasoning (Gemini thinking) before it acts.

    Non-streaming: the whole thinking block of a turn arrives at once, so this
    event is yielded ONCE per turn (not as deltas). The CLI renders it dimmed,
    separate from the main answer."""
    model_config = ConfigDict(frozen=True)

    type: Literal["thought"] = "thought"
    text: str


class ToolCallStartEvent(BaseModel):
    """Agent is starting a tool call. The CLI prints it so the user sees what's running."""
    model_config = ConfigDict(frozen=True)

    type: Literal["tool_call_start"] = "tool_call_start"
    tool_name: str
    arguments: dict


class ToolCallEndEvent(BaseModel):
    """Tool call finished. `ok=False` when the tool failed (doesn't exist,
    bad args, or _run raised)."""
    model_config = ConfigDict(frozen=True)

    type: Literal["tool_call_end"] = "tool_call_end"
    tool_name: str
    ok: bool


class AgentFinishEvent(BaseModel):
    """Loop ended normally — the assistant stopped calling tools."""
    model_config = ConfigDict(frozen=True)

    type: Literal["agent_finish"] = "agent_finish"


class AgentErrorEvent(BaseModel):
    """Loop stopped due to an error: max_iterations, a provider exception,
    or stop_reason='error'."""
    model_config = ConfigDict(frozen=True)

    type: Literal["agent_error"] = "agent_error"
    message: str


AgentEvent = (
    LoadingEvent
    | AssistantTextEvent
    | ThoughtEvent
    | ToolCallStartEvent
    | ToolCallEndEvent
    | AgentFinishEvent
    | AgentErrorEvent
)
