"""CLI entry point — orchestrate config -> provider -> agent + harness + session.

v2 changes:
- Wire AgentHarness (instead of calling the Agent directly)
- Wire up SessionStore; each tap run = one new session
- Add slash commands: /sessions, /resume, /new, /help
-Pass project_root to the tools (Path.cwd()) + prompt (reads AGENTS.md)
"""

from __future__ import annotations

import argparse
import os 
import sys
import truststore
truststore.inject_into_ssl()

from pathlib import Path

from pydantic import ValidationError

from tap.agent import Agent
from tap.config import Settings, thinking_budget_from_level
from tap.events import (
    AgentErrorEvent,
    AgentEvent,
    AgentFinishEvent,
    AssistantTextEvent,
    LoadingEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from tap.harness import AgentHarness
from tap.prompt import build_system_prompt
from tap.skills import load_skills, skill_roots
from tap.providers.gemini import GeminiProvider
from tap.storage import Session, SessionStore
from tap.tools.bash import BashTool
from tap.tools.edit import EditTool
from tap.tools.plan import PlanTool, PlanState
from tap.tools.read import ReadTool
from tap.tools.registry import ToolRegistry
from tap.tools.write import WriteTool

SEPARATOR = "─" * 50
DEFAULT_MODEL = Settings.model_fields["tap_model"].default

UI_TEXT = {
    "en": {
        "missing_key": "[!] GEMINI_API_KEY was not found in the environment or .env file.",
        "enter_key_now": "    Enter the key now (for this session only),",
        "add_key_later": "    or press Ctrl+C to exit and add it to .env for future runs.",
        "prompt_key": "    Gemini API key: ",
        "cancelled": "\n[!] Cancelled.",
        "empty_key": "[!] Empty key. Exiting.",
        "select_model": "[i] Select a model:",
        "default_model": "    1) {model} (default)",
        "custom_model": "    2) Enter a custom model",
        "select_choice": "    Select [1]: ",
        "enter_model_name": "    Enter model name: ",
        "using_model": "[i] Using model: {model}",
        "config_failed": "[!] Configuration still failed after entering the key:",
        "using_key": "[i] Using Gemini key ...{tail} (source: {source})",
        "select_ui_language": "[i] Select UI language:",
        "ui_language_en": "    1) English",
        "ui_language_vi": "    2) Tiếng Việt",
        "ui_language_choice": "    Select [1]: ",
        "ui_language_selected": "[i] UI language set to: {language}",
        "select_reply_language": "[i] Choose the reply language for the agent:",
        "reply_language_auto": "    1) Auto (match the user's language)",
        "reply_language_vi": "    2) Vietnamese",
        "reply_language_en": "    3) English",
        "reply_language_choice": "    Select [1]: ",
        "reply_language_selected": "[i] Agent reply language set to: {language}",
        "no_sessions": "(no sessions yet)",
        "help_prompt": "/help for commands, /exit or Ctrl-D to quit.",
        "help_text": """Slash commands:
  /help              — show this help
  /exit, /quit       — exit tap
  /plan              — view the current plan
  /clear             — reset the current session transcript (does not delete the file)
  /sessions          — list saved sessions
  /show [id]         — review session content (default: current session)
  /resume <id>       — load an older session and continue
  /new               — end the current session and start a new one
""",
        "reset_session": "[Reset the current session transcript]",
        "unknown_command": "[!] Unknown command: {line}. Type /help to see the list.",
        "cancel_run": "[!] Cancelled the current run (Ctrl+C). Continue typing or use /exit to quit.",
        "agent_error": "[!] Error while calling the agent: {type_name}: {error}",
        "empty_session": "(empty session)",
        "tap_banner": "tap — mini coding agent",
        "session_label": "Session: {session_id}",
        "error_main": "[!] Error: {type_name}: {error}",
        "more_lines": "  ... ({remaining} more lines, open the JSONL file to view the full output)",
    },
    "vi": {
        "missing_key": "[!] Không tìm thấy GEMINI_API_KEY trong môi trường hoặc file .env.",
        "enter_key_now": "    Nhập key ngay bây giờ (chỉ dùng cho phiên này),",
        "add_key_later": "    hoặc nhấn Ctrl+C để thoát và thêm vào .env cho lần sau.",
        "prompt_key": "    Gemini API key: ",
        "cancelled": "\n[!] Đã hủy.",
        "empty_key": "[!] Key rỗng. Thoát.",
        "select_model": "[i] Chọn model:",
        "default_model": "    1) {model} (mặc định)",
        "custom_model": "    2) Nhập model khác",
        "select_choice": "    Chọn [1]: ",
        "enter_model_name": "    Nhập tên model: ",
        "using_model": "[i] Đang dùng model: {model}",
        "config_failed": "[!] Vẫn lỗi cấu hình sau khi nhập key:",
        "using_key": "[i] Đang dùng Gemini key ...{tail} (nguồn: {source})",
        "select_ui_language": "[i] Chọn ngôn ngữ giao diện:",
        "ui_language_en": "    1) English",
        "ui_language_vi": "    2) Tiếng Việt",
        "ui_language_choice": "    Chọn [1]: ",
        "ui_language_selected": "[i] Ngôn ngữ giao diện đã đặt: {language}",
        "select_reply_language": "[i] Chọn chế độ ngôn ngữ trả lời của agent:",
        "reply_language_auto": "    1) Tự động (theo ngôn ngữ của người dùng)",
        "reply_language_vi": "    2) Tiếng Việt",
        "reply_language_en": "    3) Tiếng Anh",
        "reply_language_choice": "    Chọn [1]: ",
        "reply_language_selected": "[i] Chế độ trả lời của agent đã đặt: {language}",
        "no_sessions": "(chưa có session nào)",
        "help_prompt": "/help để xem lệnh, /exit hoặc Ctrl-D để thoát.",
        "help_text": """Lệnh slash:
  /help              — hiển thị help này
  /exit, /quit       — thoát tap
  /plan              — xem kế hoạch hiện tại
  /clear             — reset transcript của session hiện tại (không xóa file)
  /sessions          — liệt kê các session đã lưu
  /show [id]         — xem lại nội dung session (mặc định: session hiện tại)
  /resume <id>       — tải session cũ và tiếp tục
  /new               — kết thúc session hiện tại và bắt đầu session mới
""",
        "reset_session": "[Đã reset transcript của session hiện tại]",
        "unknown_command": "[!] Lệnh không hợp lệ: {line}. Gõ /help để xem danh sách.",
        "cancel_run": "[!] Đã hủy run hiện tại (Ctrl+C). Gõ tiếp hoặc /exit để thoát.",
        "agent_error": "[!] Lỗi khi gọi agent: {type_name}: {error}",
        "empty_session": "(session rỗng)",
        "tap_banner": "tap — mini coding agent",
        "session_label": "Session: {session_id}",
        "error_main": "[!] Lỗi: {type_name}: {error}",
        "more_lines": "  ... ({remaining} dòng nữa, mở file JSONL để xem full)",
    },
}


def normalize_ui_language(value: str | None) -> str:
    """Normalize the UI language and keep only supported values."""
    lang = (value or "en").strip().lower()
    return lang if lang in {"en", "vi"} else "en"


def ui_text(key: str, ui_language: str | None = None, **kwargs: object) -> str:
    """Render a user-facing string for the selected UI language."""
    language = normalize_ui_language(ui_language)
    template = UI_TEXT.get(language, UI_TEXT["en"]).get(key, UI_TEXT["en"][key])
    return template.format(**kwargs)


def _prompt_for_key(ui_language: str | None = None) -> None:
    """No key found -> prompt for one, set it in os.environ for the current session."""
    print(ui_text("missing_key", ui_language))
    print(ui_text("enter_key_now", ui_language))
    print(ui_text("add_key_later", ui_language))
    try:
        key = input(ui_text("prompt_key", ui_language)).strip()
    except (KeyboardInterrupt, EOFError):
        print(ui_text("cancelled", ui_language))
        sys.exit(1)
    if not key:
        print(ui_text("empty_key", ui_language))
        sys.exit(1)
    os.environ["GEMINI_API_KEY"] = key  # pydantic Settings will re-read from here


def _prompt_for_model(ui_language: str | None = None) -> None:
    """Prompt for a model choice, set it in os.environ for the current session."""
    print(ui_text("select_model", ui_language))
    print(ui_text("default_model", ui_language, model=DEFAULT_MODEL))
    print(ui_text("custom_model", ui_language))
    try:
        choice = input(ui_text("select_choice", ui_language)).strip()
    except (KeyboardInterrupt, EOFError):
        choice = "1"  # Ctrl+C here -> use the default, don't fully exit

    if choice == "2":
        try:
            model = input(ui_text("enter_model_name", ui_language)).strip()
        except (KeyboardInterrupt, EOFError):
            model = ""
        model = model or DEFAULT_MODEL  # empty input -> fall back to the default
    else:
        model = DEFAULT_MODEL  # "1", Enter, or any garbage -> default

    os.environ["TAP_MODEL"] = model  # pydantic Settings will re-read it
    print(ui_text("using_model", ui_language, model=model))


def _prompt_for_ui_language() -> str:
    """Ask the user to choose the UI language for this session."""
    ui_language = normalize_ui_language(os.environ.get("TAP_UI_LANGUAGE"))
    print(ui_text("select_ui_language", ui_language))
    print(ui_text("ui_language_en", ui_language))
    print(ui_text("ui_language_vi", ui_language))
    try:
        choice = input(ui_text("ui_language_choice", ui_language)).strip()
    except (KeyboardInterrupt, EOFError):
        choice = "1"

    if choice == "2":
        ui_language = "vi"
    else:
        ui_language = "en"

    os.environ["TAP_UI_LANGUAGE"] = ui_language
    print(ui_text("ui_language_selected", ui_language, language=ui_language))
    return ui_language


def _prompt_for_reply_language(ui_language: str | None = None) -> str:
    """Ask the user to choose the agent reply language mode."""
    current = (os.environ.get("TAP_LANGUAGE") or "auto").strip().lower()
    if current not in {"auto", "vi", "en", "ja", "ko"}:
        current = "auto"

    print(ui_text("select_reply_language", ui_language))
    print(ui_text("reply_language_auto", ui_language))
    print(ui_text("reply_language_vi", ui_language))
    print(ui_text("reply_language_en", ui_language))
    try:
        choice = input(ui_text("reply_language_choice", ui_language)).strip()
    except (KeyboardInterrupt, EOFError):
        choice = "1"

    if choice == "2":
        chosen = "vi"
    elif choice == "3":
        chosen = "en"
    else:
        chosen = "auto"

    os.environ["TAP_LANGUAGE"] = chosen
    print(ui_text("reply_language_selected", ui_language, language=chosen))
    return chosen


def load_settings() -> Settings:
    """Load Settings; if the key is missing, prompt and retry. Print the key's tail + its source."""
    key_before = os.environ.get("GEMINI_API_KEY")  # present already = from a real env var
    ui_language = normalize_ui_language(os.environ.get("TAP_UI_LANGUAGE"))

    try:
        settings = Settings()
    except ValidationError:
        _prompt_for_key(ui_language)
        if "TAP_MODEL" not in os.environ:  
            _prompt_for_model(ui_language)  
        try:
            settings = Settings()  # retry after injecting the key
        except ValidationError as e:
            print(ui_text("config_failed", ui_language), file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(1)

    if "TAP_LANGUAGE" not in os.environ:
        _prompt_for_reply_language(ui_language)
        settings = Settings()

    key = settings.gemini_api_key
    source = "env var" if key_before else ".env / manual entry"
    print(ui_text("using_key", ui_language, tail=key[-4:], source=source))
    return settings

def build_agent_and_harness(
    session: Session,
    project_root: Path,
    settings: Settings | None = None,
) -> tuple[Agent, AgentHarness, PlanState]:
    """Load config, initialize everything, and wire it all together.

    Returns (agent, harness) — the CLI needs the agent to load a past session on /resume.
    """

    if settings is None:
        settings = load_settings()

    provider = GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.tap_model,
        thinking_budget=thinking_budget_from_level(settings.tap_thinking),
    )
    roots = skill_roots(project_root)
    skills = load_skills(roots)

    plan_state = PlanState()
    tools = [
        # Only read is widened to the skill roots; write/edit/bash stay locked to the project.
        ReadTool(project_root=project_root, extra_read_roots=roots),
        BashTool(project_root=project_root),
        WriteTool(project_root=project_root),
        EditTool(project_root=project_root),
        PlanTool(plan_state),
    ]
    registry = ToolRegistry(tools)
    system = build_system_prompt(
        tools, 
        project_root=project_root, 
        skills=skills,
        language=settings.tap_language,
        )

    agent = Agent(
        provider=provider,
        tools=tools,
        system=system,
        max_iterations=settings.tap_max_iterations,
        on_message=session.append,
    )
    harness = AgentHarness(
        agent=agent,
        tool_executor=registry.execute,
    )
    return agent, harness, plan_state


def _format_args(args: dict) -> str:
    """Format arguments concisely for CLI display."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        if isinstance(v, str):
            s = v
            if len(s) > 50:
                s = s[:47] + "..."
            parts.append(f"{k}={s!r}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)

def _render_message_for_show(msg) -> None:
    """Format one message for /show. Truncate tool output for brevity."""
    TOOL_OUTPUT_MAX_LINES = 20

    if msg.role == "user":
        print("💬 user")
        for line in msg.content.splitlines() or [""]:
            print(f"  {line}")
        print()

    elif msg.role == "assistant":
        # Assistant may have text, tool_calls, or both
        if msg.text:
            print("🤖 assistant")
            for line in msg.text.splitlines():
                print(f"  {line}")
            print()
        for call in msg.tool_calls:
            args_str = _format_args(call.arguments)
            print(f"🤖 assistant → tool_call")
            print(f"  {call.name}({args_str})")
            print()

    elif msg.role == "tool":
        mark = "✓" if msg.ok else "✗"
        print(f"🔧 tool: {msg.name} {mark}")
        lines = msg.content.splitlines()
        for line in lines[:TOOL_OUTPUT_MAX_LINES]:
            print(f"  {line}")
        if len(lines) > TOOL_OUTPUT_MAX_LINES:
            remaining = len(lines) - TOOL_OUTPUT_MAX_LINES
            print(f"  ... ({remaining} more lines, open the JSONL file to view the full output)")
        print()

def _render_repl_event(event: AgentEvent) -> None:
    """Render an event to stdout for REPL mode."""
    match event.type:
        case "loading":
            print("⟳ Loading...", flush=True)

        case "thought":
            dim, reset = "\033[2m", "\033[0m"
            for line in event.text.splitlines():
                print(f"{dim}  💭 {line}{reset}", flush=True)

        case "tool_call_start":
            args_str = _format_args(event.arguments)
            print(f"  → {event.tool_name}({args_str})", flush=True)

        case "tool_call_end":
            mark = "✓" if event.ok else "✗"
            status = "done" if event.ok else "failed"
            print(f"  {mark} {event.tool_name} {status}", flush=True)

        case "assistant_text":
            print(f"\n🤖 tap> {event.text}", flush=True)

        case "agent_finish":
            print("\n✨ Tap is finished!", flush=True)
            print(SEPARATOR, flush=True)

        case "agent_error":
            print(f"\n[!] {event.message}", flush=True)
            print(SEPARATOR, flush=True)


def build_help_text(ui_language: str | None = None) -> str:
    """Return the slash-command help text in the selected UI language."""
    return ui_text("help_text", normalize_ui_language(ui_language))


def _cmd_sessions(store: SessionStore, ui_language: str | None = None) -> None:
    summaries = store.list_sessions()
    if not summaries:
        print(ui_text("no_sessions", ui_language))
        return
    print(f"{'ID':<20} {'Msgs':>5}  {'Updated':<20} First message")
    print("─" * 90)
    for s in summaries:
        updated = s.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{s.id:<20} {s.message_count:>5}  {updated:<20} {s.first_user_message}")


def _cmd_resume(
    session_id: str,
    store: SessionStore,
    agent: Agent,
) -> Session | None:
    """Load a past session into the agent, returning a new Session object (appends to the same file)."""
    try:
        messages = store.load(session_id)
        new_session_handle = store.open_existing(session_id)
    except FileNotFoundError as e:
        print(f"[!] {e}")
        return None

    agent.load_messages(messages)
    agent.set_on_message(new_session_handle.append)
    print(f"[Resumed session {session_id} — {len(messages)} messages loaded]\n")
    return new_session_handle

def _cmd_show(
    session_id: str | None,
    store: SessionStore,
    current_session: Session,
    ui_language: str | None = None,
) -> None:
    """Render a session to the terminal so the user can review its contents.

    Read-only: doesn't load into the transcript, doesn't change state. To keep
    chatting from a past session, use /resume.
    """
    target_id = session_id or current_session.id
    try:
        messages = store.load(target_id)
    except FileNotFoundError as e:
        print(f"[!] {e}")
        return

    print(f"\n─── Session {target_id} ({len(messages)} messages) ───\n")

    if not messages:
        print(f"{ui_text('empty_session', ui_language)}\n")
        return

    for msg in messages:
        _render_message_for_show(msg)

    print(SEPARATOR)


def _cmd_new(store: SessionStore, agent: Agent) -> Session:
    """End the current session and create a new one."""
    new_session = store.new_session()
    agent.reset()
    agent.set_on_message(new_session.append)
    print(f"[New session started: {new_session.id}]\n")
    return new_session


def run_repl(
    agent: Agent,
    harness: AgentHarness,
    store: SessionStore,
    current_session: Session,
    plan_state: PlanState,
    ui_language: str | None = None,
) -> None:
    """Interactive REPL mode with slash commands."""
    ui_language = normalize_ui_language(ui_language)
    print(ui_text("tap_banner", ui_language))
    print(ui_text("session_label", ui_language, session_id=current_session.id))
    print(f"{ui_text('help_prompt', ui_language)}\n")

    while True:
        try:
            line = input("💬 user> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Bye! See you next time.")
            break

        if not line:
            continue

        # Slash commands
        if line in {"/exit", "/quit"}:
            print("👋 Bye! See you next time.")
            break

        if line == "/help":
            print(build_help_text(ui_language))
            continue

        if line == "/plan":
            print(plan_state.render(), "\n")
            continue
        
        if line == "/clear":
            agent.reset()
            print(f"{ui_text('reset_session', ui_language)}\n")
            continue

        if line == "/sessions":
            _cmd_sessions(store, ui_language)
            print()
            continue

        if line.startswith("/resume"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /resume <session_id>\n")
                continue
            new_handle = _cmd_resume(parts[1].strip(), store, agent)
            if new_handle is not None:
                current_session = new_handle
            continue

        if line.startswith("/show"):
            parts = line.split(maxsplit=1)
            target_id = parts[1].strip() if len(parts) > 1 else None
            _cmd_show(target_id, store, current_session, ui_language)
            continue

        if line == "/new":
            current_session = _cmd_new(store, agent)
            continue

        if line.startswith("/"):
            print(ui_text("unknown_command", ui_language, line=line) + "\n")
            continue

        # Regular chat
        try:
            for event in harness.chat(line):
                _render_repl_event(event)
                # After the plan updates, print the checklist for the user to see.
                if (
                    event.type == "tool_call_end"
                    and event.tool_name == "update_plan"
                    and event.ok
                ):
                    print(plan_state.render(), flush=True)
        except KeyboardInterrupt:
            # Ctrl+C mid-run: cancel the current run, but do NOT exit tap.
            # The transcript keeps whatever was appended up to now (the session file
            # is append-only, so it isn't corrupted); the user can type again right away.
            print(f"\n{ui_text('cancel_run', ui_language)}", flush=True)
        except Exception as e:
            print(
                f"\n{ui_text('agent_error', ui_language, type_name=type(e).__name__, error=e)}",
                file=sys.stderr,
                flush=True,
            )

        print()  # blank line separator


def run_one_shot(harness: AgentHarness, prompt: str) -> int:
    """1-shot mode: final text -> stdout, tool activity -> stderr."""
    final_texts: list[str] = []
    had_error = False

    for event in harness.chat(prompt):
        match event.type:
            case "loading":
                pass

            case "thought":
                for line in event.text.splitlines():
                    print(f"  💭 {line}", file=sys.stderr, flush=True)

            case "assistant_text":
                final_texts.append(event.text)

            case "tool_call_start":
                args_str = _format_args(event.arguments)
                print(
                    f"  → {event.tool_name}({args_str})",
                    file=sys.stderr,
                    flush=True,
                )

            case "tool_call_end":
                mark = "✓" if event.ok else "✗"
                print(
                    f"  {mark} {event.tool_name}",
                    file=sys.stderr,
                    flush=True,
                )

            case "agent_error":
                print(f"[!] {event.message}", file=sys.stderr, flush=True)
                had_error = True

            case "agent_finish":
                pass

    if final_texts:
        print(final_texts[-1], flush=True)

    return 1 if had_error else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tap",
        description="A mini coding agent for the terminal (v4).",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="One-shot prompt. Leave empty to open the interactive REPL.",
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=Path.cwd() / ".tap-sessions",
        help="Directory for storing sessions (default: ./.tap-sessions in the project)",
    )
    parser.add_argument(
        "--ui-language",
        choices=["en", "vi"],
        default=None,
        help="Interface language for user-facing prompts and slash commands: en or vi.",
    )
    args = parser.parse_args()

    if args.ui_language is not None:
        ui_language = normalize_ui_language(args.ui_language)
    elif "TAP_UI_LANGUAGE" in os.environ:
        ui_language = normalize_ui_language(os.environ.get("TAP_UI_LANGUAGE"))
    else:
        ui_language = _prompt_for_ui_language()
    os.environ["TAP_UI_LANGUAGE"] = ui_language

    settings = load_settings()
    ui_language = settings.tap_ui_language

    project_root = Path.cwd()
    store = SessionStore(session_dir=args.session_dir)
    current_session = store.new_session()

    agent, harness, plan_state = build_agent_and_harness(
        session=current_session,
        project_root=project_root,
        settings=settings,
    )

    if args.prompt:
        try:
            exit_code = run_one_shot(harness, args.prompt)
        except Exception as e:
            print(ui_text("error_main", ui_language, type_name=type(e).__name__, error=e), file=sys.stderr)
            sys.exit(1)
        sys.exit(exit_code)
    else:
        run_repl(agent, harness, store, current_session, plan_state, ui_language)


if __name__ == "__main__":
    main()
    