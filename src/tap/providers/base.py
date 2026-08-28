"""Provider protocol — every provider must conform to this.

Provider has one job: take `list[Message]` + `list[BaseTool]` + `system`,
and return an `AssistantMessage`. It must know NOTHING about the registry, the CLI,
the filesystem, or the agent loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from tap.messages import AssistantMessage, Message

if TYPE_CHECKING:
    from tap.tools.base import BaseTool


class BaseProvider(Protocol):
    def generate(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list["BaseTool"],
    ) -> AssistantMessage:
        """Generate 1 assistant turn.

        Args:
            system: System prompt.
            messages: Full curent transcript.
            tools: Tools available to LLM on this turn.

        Returns:
            AssistantMessage with text and/or tool_calls.
            Do NOT raise when the model refuses — return with explanatory text.
            RAISE on network/auth errors — the agent will catch and report to the user.
        """
        ...
