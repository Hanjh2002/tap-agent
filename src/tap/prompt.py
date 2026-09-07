""" 
System prompt builder.

v1: Read `AGENTS.md` from `project_root`, if present, and inject its
contents into the system prompt.

This follows a convention-over-configuration approach: each repository can
provide a short `AGENTS.md` file containing project-specific context such as
frameworks, conventions, and architecture. If the file is absent, the system
prompt remains unchanged.

The `AGENTS.md` filename follows a convention used by several AI coding
agents, allowing the same project-level instructions to be shared across
compatible tools.

v2: Include a skill index containing the name, description, and location of
each available skill.

The index contains metadata only. The body of each `SKILL.md` is not loaded
here. When a task matches a skill's description, the model can use the `read`
tool to load the skill from its `<location>`. This follows a progressive
disclosure approach: load skill instructions only when they are relevant.

Because skill instructions are loaded through the `read` tool, the skill
index is included only when the `read` tool is available.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from tap.skills import Skill
from tap.tools.base import BaseTool

CONTEXT_FILENAME = "AGENTS.md"

# Prevent an overly long AGENTS.md from consuming too much context
MAX_CONTEXT_CHARS = 20_000  


IDENTITY = """
You are tap, a coding agent running in the terminal.

Your responsibilities:
- Read files and explain their contents
- Run shell commands when requested and explain the output
- Create new files or modify existing files when requested
- Answer programming questions and explain coding concepts

Working principles:
- Be concise, direct, and avoid unnecessary verbosity
- Use tools when real data is needed; do not invent file contents or command output
- If the user asks about a file you have not read, read it before answering
- If a path is unclear or the file does not exist, ask the user for the exact path instead of guessing
- If a tool returns an error, explain the error instead of silently ignoring it
- For multi-step tasks, use the `update_plan` tool to create a checklist and update its status after each step
- When writing or modifying code, run the code or its tests and inspect the real output before concluding that the task is complete
- If a fix still fails, inspect the error carefully, identify the root cause, and make the smallest targeted correction
- If the same error persists after two attempts, stop and report what was tried instead of guessing further
"""


def _has_tool(tools: list[BaseTool], name: str) -> bool:
    """True if a tool named `name` is in the list."""
    return any(tool.name == name for tool in tools)


def _read_project_context(project_root: Path) -> str | None:
    """Read AGENTS.md if present, truncating if it's too long."""
    context_file = project_root / CONTEXT_FILENAME
    if not context_file.exists() or not context_file.is_file():
        return None
    try:
        text = context_file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return None

    if len(text) > MAX_CONTEXT_CHARS:
        text = (
            text[:MAX_CONTEXT_CHARS]
            + f"\n\n[truncated at {MAX_CONTEXT_CHARS} chars]"
        )
    return text


def _format_skills_block(skills: Sequence[Skill]) -> str:
    """Build the <available_skills> block from skill metadata.

    name/description/location are all XML-escaped because they are user-controlled
    text (coming from directory names + frontmatter on disk). Without escaping,
    a description containing '<' or '</available_skills>' could break the block
    structure or inject fake tags — this is a prompt-injection surface.
    """
    entries = []
    for skill in skills:
        entries.append(
            "  <skill>\n"
            f"    <name>{escape(skill.name)}</name>\n"
            f"    <description>{escape(skill.description)}</description>\n"
            f"    <location>{escape(str(skill.path))}</location>\n"
            "  </skill>"
        )
    body = "\n".join(entries)
    return (
        "Specialized skills are available for different types of tasks. "
        "When the user's request matches a skill description, use the `read` "
        "tool to read the file at <location> and follow its instructions. "
        "Relative paths inside a skill are resolved from the directory "
        "containing that skill's SKILL.md file.\n\n"
        f"<available_skills>\n{body}\n</available_skills>"
    )


def _language_directive(language: str) -> str:
    """Build the language instruction injected into the system prompt.

    "auto"        -> mirror the user's language.
    "vi"/"en"/... -> force that specific language.
    unknown code  -> mirror the user's language.
    """
    
    language_names = {
        "vi": "Vietnamese",
        "en": "English",
        "ja": "Japanese",
        "ko": "Korean",
    }

    code = language.strip().lower()
    language_name = language_names.get(code)

    if code == "auto" or language_name is None:
        return (
            "Always respond in the same language used by the user. " 
            "Do NOT default to Vietnamese or any other language."
        )
    
    return (
        f"The language user choose is {language_name}. "
        f"ALWAYS respond in {language_name} whether the user asks by any other language."
        )

def build_system_prompt(
    tools: list[BaseTool],
    project_root: Path | None = None,
    skills: Sequence[Skill] | None = None,
    language: str = "auto",
) -> str:
    """Build system prompt: identity + tool descriptions + project context + skills.

    Args:
        tools: The list of available tools. Empty is fine.
        project_root: If given, read AGENTS.md from here and inject it into the prompt.
        skills: If given, insert the skill index. ONLY inserted when the `read` tool
            exists — because the model needs `read` to load a skill's body; advertising
            a skill it can't read is pointless.
        language: Language mode. "auto" (default) mirrors the user's language;
            a language code like "vi" or "en" forces every reply into that
            language regardless of what the user writes. Unknown codes fall
            back to mirroring.
    """
    parts = [IDENTITY]

    if tools:
        tool_lines = "\n".join(
            f"- {tool.name}: {tool.description}" for tool in tools
        )
        parts.append(f"Available tools:\n{tool_lines}")

    if project_root is not None:
        context = _read_project_context(project_root)
        if context is not None:
            parts.append(
                f"Current project context (from {CONTEXT_FILENAME}):\n{context}"
            )

    if skills and _has_tool(tools, "read"):
        parts.append(_format_skills_block(skills))

    parts.append(_language_directive(language))
    return "\n\n".join(parts)
