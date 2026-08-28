"""Test CLI wiring (Phase 2 phần cli.py).

Chỉ test phần LOGIC tách được, không test vòng REPL tương tác:
1. build_agent_and_harness: level 'high' -> provider._thinking_budget đúng.
2. _render_repl_event('thought'): in kèm mã ANSI dim, đủ mọi dòng.
3. run_one_shot: thought -> stderr, assistant_text -> stdout (chỉ text cuối),
   agent_error -> exit code 1.

Ghi chú: vòng REPL (input()/slash command) là I/O tương tác, verify tay
nhanh hơn — không cố nhồi vào test tự động.
"""

from __future__ import annotations

from types import SimpleNamespace

from tap import cli
from tap.events import (
    AgentErrorEvent,
    AgentFinishEvent,
    AssistantTextEvent,
    LoadingEvent,
    ThoughtEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)


# ---------------------------------------------------------------------------
# 1. build_agent_and_harness wire đúng thinking_budget vào provider
# ---------------------------------------------------------------------------

def test_build_wires_thinking_budget(monkeypatch, tmp_path):
    # Giả load_settings để khỏi cần .env; chỉ cần các field build_* dùng tới.
    fake_settings = SimpleNamespace(
        gemini_api_key="fake-key",
        tap_model="gemini-2.5-flash",
        tap_thinking="high",          # -> budget 24576
        tap_max_iterations=10,
    )
    monkeypatch.setattr(cli, "load_settings", lambda: fake_settings)

    session = SimpleNamespace(append=lambda _msg: None)
    agent, harness, plan_state = cli.build_agent_and_harness(
        session=session, project_root=tmp_path
    )

    # provider nằm trong agent._provider (xem agent.py)
    assert agent._provider._thinking_budget == 24576
    assert plan_state is not None


def test_build_wires_thinking_budget_off(monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(
        gemini_api_key="fake-key",
        tap_model="gemini-2.5-flash",
        tap_thinking="off",           # -> budget 0
        tap_max_iterations=10,
    )
    monkeypatch.setattr(cli, "load_settings", lambda: fake_settings)
    session = SimpleNamespace(append=lambda _msg: None)

    agent, _, _ = cli.build_agent_and_harness(session=session, project_root=tmp_path)

    assert agent._provider._thinking_budget == 0


# ---------------------------------------------------------------------------
# 2. _render_repl_event render thought mờ (dim) + đủ dòng
# ---------------------------------------------------------------------------

def test_render_thought_is_dim_and_multiline(capsys):
    cli._render_repl_event(ThoughtEvent(text="dong 1\ndong 2"))
    out = capsys.readouterr().out

    assert "\033[2m" in out   # mã dim mở
    assert "\033[0m" in out   # mã reset
    assert "dong 1" in out
    assert "dong 2" in out    # cả 2 dòng đều in


def test_render_assistant_text_not_dim(capsys):
    cli._render_repl_event(AssistantTextEvent(text="cau tra loi"))
    out = capsys.readouterr().out

    assert "cau tra loi" in out
    assert "\033[2m" not in out  # câu trả lời KHÔNG bị làm mờ


# ---------------------------------------------------------------------------
# 3. run_one_shot: thought -> stderr, answer -> stdout, error -> code 1
# ---------------------------------------------------------------------------

class _FakeHarness:
    def __init__(self, events):
        self._events = events

    def chat(self, prompt):
        return iter(self._events)


def test_one_shot_splits_stderr_stdout(capsys):
    events = [
        LoadingEvent(),
        ThoughtEvent(text="suy luan noi bo"),
        ToolCallStartEvent(tool_name="read", arguments={"path": "a.py"}),
        ToolCallEndEvent(tool_name="read", ok=True),
        AssistantTextEvent(text="ket qua cuoi"),
        AgentFinishEvent(),
    ]
    code = cli.run_one_shot(_FakeHarness(events), "lam gi do")

    captured = capsys.readouterr()
    # stdout CHỈ chứa câu trả lời cuối, sạch (để pipe được)
    assert captured.out.strip() == "ket qua cuoi"
    # thought + tool activity nằm ở stderr
    assert "suy luan noi bo" in captured.err
    assert "read" in captured.err
    # không có lỗi -> exit code 0
    assert code == 0


def test_one_shot_returns_error_code(capsys):
    events = [
        LoadingEvent(),
        AgentErrorEvent(message="something broke"),
    ]
    code = cli.run_one_shot(_FakeHarness(events), "x")

    captured = capsys.readouterr()
    assert code == 1
    assert "something broke" in captured.err


def test_one_shot_prints_only_last_text(capsys):
    # Nhiều assistant_text (intermediate + final) -> chỉ in cái CUỐI ra stdout.
    events = [
        AssistantTextEvent(text="dang lam..."),
        ToolCallStartEvent(tool_name="bash", arguments={"cmd": "ls"}),
        ToolCallEndEvent(tool_name="bash", ok=True),
        AssistantTextEvent(text="xong roi"),
        AgentFinishEvent(),
    ]
    cli.run_one_shot(_FakeHarness(events), "x")

    assert capsys.readouterr().out.strip() == "xong roi"
    