"""Test build_system_prompt — đặc biệt phần đọc AGENTS.md."""

from __future__ import annotations

from pathlib import Path

from tap.prompt import build_system_prompt


def test_prompt_without_tools_or_project(tmp_path: Path) -> None:
    """Identity only — không có gì thêm."""
    prompt = build_system_prompt(tools=[])
    assert "tap" in prompt.lower()
    assert "AGENTS.md" not in prompt  # không có project_root


def test_prompt_includes_agents_md_when_present(tmp_path: Path) -> None:
    """Có AGENTS.md → nội dung nhét vào prompt."""
    (tmp_path / "AGENTS.md").write_text(
        "# Convention\n- Use pytest\n- snake_case",
        encoding="utf-8",
    )

    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    assert "Convention" in prompt
    assert "pytest" in prompt
    assert "snake_case" in prompt
    assert "AGENTS.md" in prompt  # header nhắc filename


def test_prompt_skips_agents_md_when_absent(tmp_path: Path) -> None:
    """Không có AGENTS.md → không thêm gì."""
    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    # Không có Convention section
    assert "AGENTS.md" not in prompt or "Context của project" not in prompt


def test_prompt_truncates_huge_agents_md(tmp_path: Path) -> None:
    """AGENTS.md quá dài → truncate, không đốt hết context."""
    (tmp_path / "AGENTS.md").write_text("x" * 50_000, encoding="utf-8")

    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    assert "truncated" in prompt
    # Prompt vẫn dưới ngưỡng
    assert len(prompt) < 25_000


def test_prompt_ignores_agents_md_that_is_directory(tmp_path: Path) -> None:
    """AGENTS.md là folder (kỳ lạ) → không crash."""
    (tmp_path / "AGENTS.md").mkdir()

    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    # Vẫn build được, chỉ không có context
    assert "tap" in prompt.lower()
