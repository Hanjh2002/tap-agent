"""Test build_system_prompt — especially the AGENTS.md loading behavior."""

from __future__ import annotations

from pathlib import Path

from tap.prompt import build_system_prompt


def test_prompt_without_tools_or_project(tmp_path: Path) -> None:
    """Identity only — nothing else is added."""
    prompt = build_system_prompt(tools=[])
    assert "tap" in prompt.lower()
    assert "AGENTS.md" not in prompt  # no project_root


def test_prompt_includes_agents_md_when_present(tmp_path: Path) -> None:
    """AGENTS.md is present → its contents are injected into the prompt."""
    (tmp_path / "AGENTS.md").write_text(
        "# Convention\n- Use pytest\n- snake_case",
        encoding="utf-8",
    )

    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    assert "Convention" in prompt
    assert "pytest" in prompt
    assert "snake_case" in prompt
    assert "AGENTS.md" in prompt  # header mentions the filename


def test_prompt_skips_agents_md_when_absent(tmp_path: Path) -> None:
    """AGENTS.md is absent → nothing is added."""
    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    # No Convention section
    assert "AGENTS.md" not in prompt or "Context of project" not in prompt


def test_prompt_truncates_huge_agents_md(tmp_path: Path) -> None:
    """AGENTS.md is too large → truncate it to avoid consuming too much context."""
    (tmp_path / "AGENTS.md").write_text("x" * 50_000, encoding="utf-8")

    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    assert "truncated" in prompt
    # Prompt remains below the threshold
    assert len(prompt) < 25_000


def test_prompt_ignores_agents_md_that_is_directory(tmp_path: Path) -> None:
    """AGENTS.md is a directory (unexpected) → do not crash."""
    (tmp_path / "AGENTS.md").mkdir()

    prompt = build_system_prompt(tools=[], project_root=tmp_path)

    # The prompt is still built successfully; no project context is added
    assert "tap" in prompt.lower()


# ----------------test tap language--------------

def test_language_auto_gives_mirror_directive() -> None:
    prompt = build_system_prompt(tools=[], language="auto").lower()

    assert "same language used by the user" in prompt
    assert "do not default to vietnamese" in prompt

def test_language_vi_forces_vietnamese() -> None:
    prompt = build_system_prompt(tools=[], language="vi").lower()

    assert "always respond in vietnamese" in prompt

def test_language_en_forces_english() -> None:
    prompt = build_system_prompt(tools=[], language="en").lower()

    assert "always respond in english" in prompt

def test_language_unknown_code_mirrors() -> None:
    prompt = build_system_prompt(tools=[], language="fr").lower()

    assert "same language used by the user" in prompt
    assert "do not default to vietnamese" in prompt

def test_old_hardcoded_vietnamese_default_is_gone() -> None:
    #  This test is here to ensure that the hardcoded "vi" language code is gone.
    for lang in ("auto", "vi", "en"):
        prompt = build_system_prompt(tools=[], language=lang)

        assert "Trả lời bằng tiếng Việt trừ khi" not in prompt
