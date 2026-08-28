"""System prompt builder.

v1: read AGENTS.md from project_root (if present) and inject it into the system prompt.
This is a convention-over-configuration approach: each repo you work in can
have a short AGENTS.md file holding context about the project (framework,
conventions, architecture). If absent → nothing changes.

Filename `AGENTS.md` is a shared convention in the AI-agent community —
compatible with other agents (Aider and some other tools read the same file).

v2: insert an "index" of skills (name + description + location) if any exist.
Index lists metadata ONLY; the body of each SKILL.md is not loaded here —
the model calls the `read` tool on <location> itself when a task matches the
description (progressive disclosure). Because the mechanism relies on `read`,
the index only appears when the `read` tool is actually present.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from tap.skills import Skill
from tap.tools.base import BaseTool

CONTEXT_FILENAME = "AGENTS.md"
MAX_CONTEXT_CHARS = 20_000  # Prevent an overly long AGENTS.md from burning context


IDENTITY = """
Bạn là tap, một coding agent chạy trên terminal.

Nhiệm vụ của bạn:
- Giúp user đọc file và giải thích nội dung
- Chạy shell command khi được yêu cầu và giải thích output
- Tạo file mới hoặc sửa file có sẵn khi được yêu cầu
- Trả lời câu hỏi về code, giải thích khái niệm lập trình

Nguyên tắc làm việc:
- Trả lời ngắn gọn, trực tiếp, không dài dòng
- Dùng tool khi cần data thực tế (đọc file, chạy lệnh) — KHÔNG tự bịa nội dung
- Nếu user hỏi về file bạn chưa đọc, hãy đọc file trước rồi mới trả lời
- Nếu path không đủ rõ hoặc file không tồn tại, hỏi lại user path chính xác thay vì đoán
- Nếu tool trả về lỗi, giải thích lỗi cho user thay vì im lặng
- Trả lời bằng tiếng Việt trừ khi user dùng ngôn ngữ khác
- Với task nhiều bước, hãy gọi tool `update_plan` để lập checklist trước khi làm, rồi cập nhật status (in_progress/done) sau mỗi bước
- Khi viết hoặc sửa code, PHẢI chạy lại nó (hoặc test của nó) bằng bash và đọc output thật trước khi kết luận "đã xong" — không bao giờ tự nhận đã sửa mà chưa có bằng chứng chạy
- Khi một lần sửa vẫn lỗi: đọc kỹ thông báo lỗi, xác định nguyên nhân gốc, rồi sửa TỐI THIỂU đúng chỗ đó — không viết lại cả khối đang chạy được
- Nếu đã thử 2 lần mà vẫn lỗi giống nhau, DỪNG và báo user kèm những gì đã thử, thay vì tiếp tục sửa mò
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
        "Các skill chuyên biệt cho từng loại task. Khi yêu cầu của user khớp "
        "description của một skill, hãy dùng tool `read` đọc file ở <location> "
        "để lấy hướng dẫn đầy đủ rồi làm theo. Đường dẫn tương đối bên trong "
        "một skill được tính từ thư mục chứa file SKILL.md đó.\n\n"
        f"<available_skills>\n{body}\n</available_skills>"
    )


def build_system_prompt(
    tools: list[BaseTool],
    project_root: Path | None = None,
    skills: Sequence[Skill] | None = None,
) -> str:
    """Build system prompt: identity + tool descriptions + project context + skills.

    Args:
        tools: The list of available tools. Empty is fine.
        project_root: If given, read AGENTS.md from here and inject it into the prompt.
        skills: If given, insert the skill index. ONLY inserted when the `read` tool
            exists — because the model needs `read` to load a skill's body; advertising
            a skill it can't read is pointless.
    """
    parts = [IDENTITY]

    if tools:
        tool_lines = "\n".join(
            f"- {tool.name}: {tool.description}" for tool in tools
        )
        parts.append(f"Các tool có sẵn:\n{tool_lines}")

    if project_root is not None:
        context = _read_project_context(project_root)
        if context is not None:
            parts.append(
                f"Context của project hiện tại (từ {CONTEXT_FILENAME}):\n{context}"
            )

    if skills and _has_tool(tools, "read"):
        parts.append(_format_skills_block(skills))

    return "\n\n".join(parts)
