"""AgentHarness — drives the Agent generator and executes tools when Agent requests.

This is the "orchestrator" split out from the Agent loop. It has one responsibility:
- Consume Agent.chat() generator
- When the Agent yields a ToolCallStartEvent → call tool_executor
- Send ToolResult back to Agent via .send()
- Forward all events outward (to the CLI/frontend)

Benefits of splitting this out from the Agent:
- doesn't need to know "how" tools are executed. To wrap them
  (confirmation, logging, sandbox), swap tool_executor without touching the Agent.
- Testing the Agent with a fake executor is dead simple (a single lambda).
- Testing the Harness in isolation with a fake Agent generator.

Signature tool_executor: `Callable[[str, dict], ToolResult]`
- Input: tool_name (str), arguments (dict)
- Output: ToolResult (must not raise — if raise, Harness wraps into
  ToolResult(ok=False))
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from tap.agent import Agent
from tap.events import AgentEvent, ToolCallStartEvent
from tap.tools.base import ToolResult


ToolExecutor = Callable[[str, dict], ToolResult]


class AgentHarness:
    def __init__(
        self,
        *,
        agent: Agent,
        tool_executor: ToolExecutor,
    ):
        self._agent = agent
        self._executor = tool_executor

    def chat(self, user_input: str) -> Iterator[AgentEvent]:
        """Drive the Agent generator, execute tools as needed, forward events.

        Wrap the executor in try/except: even though ToolRegistry already wraps
        exceptions into ToolResult(ok=False), the Harness stays defensive because
        the executor can be any callable (not just the registry).
        """
        gen = self._agent.chat(user_input)
        to_send: ToolResult | None = None

        while True:
            try:
                event = gen.send(to_send)
            except StopIteration:
                return

            yield event
            to_send = None

            if isinstance(event, ToolCallStartEvent):
                to_send = self._safe_execute(event.tool_name, event.arguments)

    def _safe_execute(self, name: str, arguments: dict) -> ToolResult:
        """Executor must not raise, but being defensive is reasonable."""
        try:
            return self._executor(name, arguments)
        except Exception as e:
            return ToolResult(
                output=(
                    f"Tool executor crashed for '{name}': "
                    f"{type(e).__name__}: {e}"
                ),
                ok=False,
            )
