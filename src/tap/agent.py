"""Agent — orchestrates the loop between the Provider and tool execution.

v2 changes:
- Agent NO LONGER holds a ToolRegistry. It only knows list[BaseTool], which it
  passes to the Provider (to build function declarations). Tool execution is
  handed off to AgentHarness via the generator .send() protocol.
- chat() yields a ToolCallStartEvent, then receives a ToolResult via .send().
  This is control-flow inversion: the Agent requests, someone else executes.
- Adds an `on_message` callback to hook session persistence (whenever a new
  message appears, the session is written to JSONL). No-op if None.

The Agent only knows about:
- BaseProvider (interface)
- list[BaseTool] (to send to the provider)
- system prompt (str)
- transcript (list[Message])
- on_message callback (optional)

Agent DOESN'T know about:
- Gemini SDK or any other provider SDK
- How tools are executed (that's the Harness's work)
- Filesystem, subprocess
- input(), print()
- .env, config file
- Session storage (only know callback)
"""

from __future__ import annotations

from collections.abc import Callable, Generator

from tap.events import (
    AgentErrorEvent,
    AgentEvent,
    AgentFinishEvent,
    AssistantTextEvent,
    ThoughtEvent,
    LoadingEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from tap.messages import (
    Message,
    ToolResultMessage,
    UserMessage,
)
from tap.providers.base import BaseProvider
from tap.tools.base import BaseTool, ToolResult


# Callback type: receives the Message that was just appended to the transcript
OnMessage = Callable[[Message], None]


class Agent:
    def __init__(
        self,
        *,
        provider: BaseProvider,
        tools: list[BaseTool],
        system: str,
        max_iterations: int = 10,
        on_message: OnMessage | None = None,
    ):
        self._provider = provider
        self._tools = tools
        self._system = system
        self._max_iter = max_iterations
        self._messages: list[Message] = []
        self._on_message: OnMessage = on_message or (lambda _m: None)

    @property
    def messages(self) -> tuple[Message, ...]:
        """Immutable snapshot of the transcript."""
        return tuple(self._messages)

    def reset(self) -> None:
        """Clear the transcript to start a new conversation."""
        self._messages = []

    def load_messages(self, messages: list[Message]) -> None:
        """Load a past session into the transcript. Used by /resume.

        Note: does NOT trigger on_message for reloaded messages — they
        are already in the file.
        """
        self._messages = list(messages)

    def set_on_message(self, callback: OnMessage | None) -> None:
        """Swap the callback — used when rotating sessions (one file per session)."""
        self._on_message = callback or (lambda _m: None)

    def chat(
        self, user_input: str
    ) -> Generator[AgentEvent, ToolResult | None, None]:
        """Take user input, run the loop, and yield events step by step.

        Protocol with the Harness:
        - Yield LoadingEvent / AssistantTextEvent / AgentFinishEvent /
          AgentErrorEvent / ToolCallEndEvent: the Harness just forwards them,
          gen.send(None).
        - Yield ToolCallStartEvent: the Harness MUST execute the tool and
          gen.send(ToolResult(...)). If it send(None) → the Agent yields
          AgentErrorEvent and stops.

        Typical event sequence:
            LoadingEvent
            -> AssistantTextEvent (if the assistant has text)
            -> ToolCallStartEvent (waits for the Harness to send a ToolResult)
            -> ToolCallEndEvent
            -> (repeat)
            -> AgentFinishEvent (normal termination)
            HOẶC AgentErrorEvent (error)

        Loop stops when:
        - Assistant stops calling tools (end_turn) -> AgentFinishEvent
        - Reached max_iterations -> AgentErrorEvent
        - Provider raise exception -> AgentErrorEvent
        - stop_reason == "error" -> AgentErrorEvent
        - Harness fail to send ToolResult back -> AgentErrorEvent
        """
        user_msg = UserMessage(content=user_input)
        self._messages.append(user_msg)
        self._on_message(user_msg)

        for _ in range(self._max_iter):
            yield LoadingEvent()

            try:
                assistant = self._provider.generate(
                    system=self._system,
                    messages=self._messages,
                    tools=self._tools,
                )
            except Exception as e:
                yield AgentErrorEvent(
                    message=f"Provider error: {type(e).__name__}: {e}"
                )
                return

            self._messages.append(assistant)
            self._on_message(assistant)

            # Reasoning (if any) is shown BEFORE the answer/action.
            if assistant.thinking:
                yield ThoughtEvent(text=assistant.thinking)

            if assistant.text:
                yield AssistantTextEvent(text=assistant.text)

            if assistant.stop_reason == "error":
                yield AgentErrorEvent(
                    message=assistant.text or "Provider returned error"
                )
                return

            if not assistant.tool_calls:
                yield AgentFinishEvent()
                return

            for call in assistant.tool_calls:
                # Yield ToolCallStart, wait for the Harness to send a ToolResult back
                result = yield ToolCallStartEvent(
                    tool_name=call.name,
                    arguments=call.arguments,
                )

                if result is None:
                    # Harness violated the protocol — a bug or a bad test setup
                    yield AgentErrorEvent(
                        message=(
                            f"Harness did not return a ToolResult for "
                            f"tool call '{call.name}'. Protocol violation."
                        )
                    )
                    return

                tool_result_msg = ToolResultMessage(
                    tool_call_id=call.id,
                    name=call.name,
                    content=result.output,
                    ok=result.ok,
                )
                self._messages.append(tool_result_msg)
                self._on_message(tool_result_msg)

                yield ToolCallEndEvent(tool_name=call.name, ok=result.ok)

        yield AgentErrorEvent(
            message=f"Đạt max_iterations={self._max_iter}, dừng loop"
        )
