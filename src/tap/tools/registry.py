"""Tool registry — the intermediary between the Agent and the Tools.

Registry handles:
1. Index tool according to name (O(1) lookup)
2. Listing tools (to build the system prompt + send to the LLM)
3. Wrapping errors into ToolResult(ok=False) — the "tool error ≠ crash" principle

Agent ust calls registry.execute(name, args), without knowing the details.
"""

from __future__ import annotations

from tap.tools.base import BaseTool, ToolResult


class ToolRegistry:
    def __init__(self, tools: list[BaseTool]):
        self._tools: dict[str, BaseTool] = {t.name: t for t in tools}

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def execute(self, name: str, arguments: dict) -> ToolResult:
        """A safe facade: lookup + execute + wrap errors.

        Agent calls this. Every error becomes a ToolResult(ok=False),never a 
        raise. The LLM will read the error message and handle it itself.
        """
        tool = self.get(name)
        if tool is None:
            available = ", ".join(self._tools) or "(none)"
            return ToolResult(
                output=f"Unknown tool: '{name}'. Available: {available}",
                ok=False,
            )
        try:
            return tool.execute(arguments)
        except Exception as e:
            return ToolResult(
                output=f"Tool '{name}' crashed unexpectedly: {type(e).__name__}: {e}",
                ok=False,
            )
