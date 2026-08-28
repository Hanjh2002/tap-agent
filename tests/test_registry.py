"""Test ToolRegistry."""

from __future__ import annotations

from pydantic import BaseModel

from tap.tools.base import BaseTool, ToolResult
from tap.tools.registry import ToolRegistry


# ---------- Fake tools cho test ----------

class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo the input text"
    args_model = EchoArgs

    def _run(self, args: EchoArgs) -> ToolResult:
        return ToolResult(output=args.text)


class CrashingTool(BaseTool):
    name = "crash"
    description = "Always raises"
    args_model = EchoArgs

    def _run(self, args: EchoArgs) -> ToolResult:
        raise RuntimeError("boom!")


# ---------- Tests ----------

def test_registry_lookup_by_name() -> None:
    tool = EchoTool()
    registry = ToolRegistry([tool])

    assert registry.get("echo") is tool
    assert registry.get("nonexistent") is None


def test_registry_all_returns_list() -> None:
    tool1 = EchoTool()
    registry = ToolRegistry([tool1])

    assert registry.all() == [tool1]


def test_registry_execute_success() -> None:
    registry = ToolRegistry([EchoTool()])

    result = registry.execute("echo", {"text": "hi"})

    assert result.ok is True
    assert result.output == "hi"


def test_registry_execute_unknown_tool() -> None:
    """Unknown tool → ToolResult(ok=False), KHÔNG raise."""
    registry = ToolRegistry([EchoTool()])

    result = registry.execute("nonexistent", {})

    assert result.ok is False
    assert "unknown tool" in result.output.lower()
    assert "echo" in result.output  # gợi ý tool có sẵn


def test_registry_execute_invalid_args() -> None:
    """Args sai → ToolResult(ok=False), KHÔNG raise."""
    registry = ToolRegistry([EchoTool()])

    result = registry.execute("echo", {"wrong_field": "hi"})

    assert result.ok is False


def test_registry_catches_tool_exception() -> None:
    """Tool crash → ToolResult(ok=False), KHÔNG propagate exception."""
    registry = ToolRegistry([CrashingTool()])

    result = registry.execute("crash", {"text": "hi"})

    assert result.ok is False
    assert "crashed" in result.output.lower()
    assert "boom" in result.output
