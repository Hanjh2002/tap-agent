"""Test Phase 1 — plan tool + schema cleaner inline $ref.

Ba nhóm:
1. PlanTool.execute: args hợp lệ ghi vào state + trả checklist; args sai ->
   ToolResult(ok=False) không raise; gọi lại rewrite cả list (re-plan).
2. PlanState.render: rỗng, và glyph đúng theo status.
3. _clean_schema_for_gemini: schema của plan tool (nested model) sau khi clean
   KHÔNG còn $ref/$defs — đây là bug đã vá ở Phase 1, test này khoá nó lại.
"""

from __future__ import annotations

import json

from tap.providers.gemini import _clean_schema_for_gemini
from tap.tools.plan import PlanState, PlanStep, PlanTool


# ---------------------------------------------------------------------------
# 1. PlanTool.execute
# ---------------------------------------------------------------------------

def test_execute_valid_writes_state_and_returns_checklist():
    state = PlanState()
    tool = PlanTool(state)

    result = tool.execute({
        "steps": [
            {"content": "Đọc cấu trúc project", "status": "done"},
            {"content": "Viết plan tool", "status": "in_progress"},
            {"content": "Wire vào CLI", "status": "pending"},
        ]
    })

    assert result.ok is True
    assert len(state.steps) == 3
    assert state.steps[0].content == "Đọc cấu trúc project"
    assert state.steps[1].status == "in_progress"
    assert "📋 Plan:" in result.output
    assert "Wire vào CLI" in result.output


def test_execute_defaults_status_to_pending():
    state = PlanState()
    tool = PlanTool(state)

    result = tool.execute({"steps": [{"content": "Bước không ghi status"}]})

    assert result.ok is True
    assert state.steps[0].status == "pending"


def test_execute_invalid_status_returns_error_not_raise():
    state = PlanState()
    tool = PlanTool(state)

    result = tool.execute({"steps": [{"content": "x", "status": "WRONG"}]})

    assert result.ok is False
    assert "Invalid arguments" in result.output
    assert state.steps == []


def test_execute_missing_steps_returns_error():
    state = PlanState()
    tool = PlanTool(state)

    result = tool.execute({})

    assert result.ok is False
    assert state.steps == []


def test_re_plan_overwrites_whole_list():
    state = PlanState()
    tool = PlanTool(state)

    tool.execute({"steps": [
        {"content": "A", "status": "pending"},
        {"content": "B", "status": "pending"},
    ]})
    tool.execute({"steps": [{"content": "C", "status": "in_progress"}]})

    assert len(state.steps) == 1
    assert state.steps[0].content == "C"


# ---------------------------------------------------------------------------
# 2. PlanState.render
# ---------------------------------------------------------------------------

def test_render_empty():
    assert PlanState().render() == "(kế hoạch trống)"


def test_render_glyphs_match_status():
    state = PlanState()
    state.set_steps([
        PlanStep(content="đã xong", status="done"),
        PlanStep(content="đang làm", status="in_progress"),
        PlanStep(content="chờ", status="pending"),
    ])
    out = state.render()

    assert "✓ 1. đã xong" in out
    assert "▶ 2. đang làm" in out
    assert "☐ 3. chờ" in out


# ---------------------------------------------------------------------------
# 3. Schema cleaner — nested model không để sót $ref/$defs
# ---------------------------------------------------------------------------

def test_plan_schema_has_no_ref_after_cleaning():
    tool = PlanTool(PlanState())
    cleaned = _clean_schema_for_gemini(tool.input_schema)
    blob = json.dumps(cleaned)

    assert "$ref" not in blob
    assert "$defs" not in blob
    items = cleaned["properties"]["steps"]["items"]
    assert items["type"] == "object"
    assert "content" in items["properties"]
    assert "status" in items["properties"]


def test_cleaner_still_strips_flat_keys():
    schema = {
        "title": "Foo",
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"title": "X", "type": "string"}},
    }
    cleaned = _clean_schema_for_gemini(schema)

    assert "title" not in cleaned
    assert "additionalProperties" not in cleaned
    assert "title" not in cleaned["properties"]["x"]
    assert cleaned["properties"]["x"]["type"] == "string"
    