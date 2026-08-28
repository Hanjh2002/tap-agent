"""Plan tool — lets the agent break a multi-step task into a checklist itself.

`Design (like other agents' TodoWrite):
- On every call, the model resends the ENTIRE step list with the current statuses.
  There's no separate "add a step" / "mark step 3 done" — the model rewrites the whole list.
  This makes re-planning natural: to change the plan, send a new list, done.
- `PlanState` is the source of truth shared between the tool and the CLI: the tool writes to it,
  the CLI reads from it to render. Just as other tools take `project_root` —
  here PlanTool takes `PlanState`.
- Tool does NOT touch the filesystem and runs NOTHING dangerous → always safe,
  no need to go through the permission layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from tap.tools.base import BaseTool, ToolResult

Status = Literal["pending", "in_progress", "done"]

_GLYPH: dict[str, str] = {
    "pending": "☐",
    "in_progress": "▶",
    "done": "✓",
}


class PlanStep(BaseModel):
    content: str = Field(..., description="The step's content, concise (one line).")
    status: Status = Field(
        default="pending",
        description="Step status: pending | in_progress | done.",
    )


class UpdatePlanArgs(BaseModel):
    steps: list[PlanStep] = Field(
        ...,
        description=(
            "The ENTIRE step list with current statuses. Resend the whole list on every "
            "update (including unchanged steps). There should be at most one "
            "'in_progress' step at a time."
        ),
    )


class PlanState:
    """Current plan — a single instance shared between PlanTool and the CLI."""

    def __init__(self) -> None:
        self.steps: list[PlanStep] = []

    def set_steps(self, steps: list[PlanStep]) -> None:
        self.steps = list(steps)

    def render(self) -> str:
        """Render the checklist for the user to see in the CLI."""
        if not self.steps:
            return "(kế hoạch trống)"
        lines = ["📋 Plan:"]
        for i, step in enumerate(self.steps, start=1):
            glyph = _GLYPH.get(step.status, "☐")
            lines.append(f"  {glyph} {i}. {step.content}")
        return "\n".join(lines)


class PlanTool(BaseTool):
    name = "update_plan"
    description = (
        "Write or update a checklist-style work plan for a multi-step task. "
        "Call it as soon as you start a complex task to break it into small steps, "
        "then call it again to mark progress (in_progress/done) as you go. "
        "Every call must RESEND the entire step list with updated statuses. "
        "Don't use it for simple one-step tasks."
    )
    args_model = UpdatePlanArgs

    def __init__(self, state: PlanState):
        self._state = state

    def _run(self, args: UpdatePlanArgs) -> ToolResult:
        self._state.set_steps(args.steps)
        # Return the rendered checklist to the model so it can confirm the current state.
        return ToolResult(output=self._state.render(), ok=True)
    