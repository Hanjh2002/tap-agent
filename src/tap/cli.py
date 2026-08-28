"""CLI entry point — orchestrate config -> provider -> agent + harness + session.

v4 changes:
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

def _prompt_for_key() -> None:
    """No key found -> prompt for one, set it in os.environ for the current session."""
    print("[!] Không tìm thấy GEMINI_API_KEY trong env var hay .env.")
    print("    Nhập key ngay bây giờ (chỉ dùng cho phiên này),")
    print("    hoặc Ctrl+C để thoát và thêm vào .env cho lần sau.")
    try:
        key = input("    Gemini API key: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Đã hủy.")
        sys.exit(1)
    if not key:
        print("[!] Key rỗng. Thoát.")
        sys.exit(1)
    os.environ["GEMINI_API_KEY"] = key  # pydantic Settings will re-read from here


def _prompt_for_model() -> None:
    """Prompt for a model choice, set it in os.environ for the current session."""
    print("[i] Chọn model:")
    print(f"    1) {DEFAULT_MODEL} (mặc định)")
    print("    2) Tự nhập model khác")
    try:
        choice = input("    Chọn [1]: ").strip()
    except (KeyboardInterrupt, EOFError):
        choice = "1"  # Ctrl+C here -> use the default, don't fully exit

    if choice == "2":
        try:
            model = input("    Nhập tên model: ").strip()
        except (KeyboardInterrupt, EOFError):
            model = ""
        model = model or DEFAULT_MODEL  # empty input -> fall back to the default
    else:
        model = DEFAULT_MODEL  # "1", Enter, or any garbage -> default

    os.environ["TAP_MODEL"] = model  # pydantic Settings will re-read it
    print(f"[i] Dùng model: {model}")


def load_settings() -> Settings:
    """Load Settings; if the key is missing, prompt and retry. Print the key's tail + its source."""
    key_before = os.environ.get("GEMINI_API_KEY")  # present already = from a real env var

    try:
        settings = Settings()
    except ValidationError:
        _prompt_for_key()
        if "TAP_MODEL" not in os.environ:  
            _prompt_for_model()  
        try:
            settings = Settings()  # retry after injecting the key
        except ValidationError as e:
            print("[!] Vẫn lỗi config sau khi nhập key:", file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(1)

    key = settings.gemini_api_key
    source = "env var" if key_before else ".env / nhập tay"
    print(f"[i] Dùng Gemini key ...{key[-4:]} (nguồn: {source})")
    return settings

def build_agent_and_harness(
    session: Session,
    project_root: Path,
) -> tuple[Agent, AgentHarness, PlanState]:
    """Load config, initialize everything, and wire it all together.

    Returns (agent, harness) — the CLI needs the agent to load a past session on /resume.
    """

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
    system = build_system_prompt(tools, project_root=project_root, skills=skills)

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
            print(f"  ... ({remaining} dòng nữa, mở file JSONL để xem full)")
        print()

def _render_repl_event(event: AgentEvent) -> None:
    """Render event ra stdout for REPL mode."""
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


HELP_TEXT = """Slash commands:
  /help              — hiện help này
  /exit, /quit       — thoát tap
  /plan              — xem kế hoạch hiện tại
  /clear             — reset transcript của session hiện tại (không xóa file)
  /sessions          — list các session đã lưu
  /show [id]         — xem lại nội dung session (mặc định: session hiện tại)
  /resume <id>       — load session cũ và tiếp tục
  /new               — kết thúc session hiện tại, bắt đầu session mới
"""


def _cmd_sessions(store: SessionStore) -> None:
    summaries = store.list_sessions()
    if not summaries:
        print("(chưa có session nào)")
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
        print("(session rỗng)\n")
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
) -> None:
    """Interactive REPL mode with slash commands."""
    print("tap — mini coding agent")
    print(f"Session: {current_session.id}")
    print("/help để xem commands, /exit hoặc Ctrl-D để thoát.\n")

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
            print(HELP_TEXT)
            continue

        if line == "/plan":
            print(plan_state.render(), "\n")
            continue
        
        if line == "/clear":
            agent.reset()
            print("[Đã reset transcript của session hiện tại]\n")
            continue

        if line == "/sessions":
            _cmd_sessions(store)
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
            _cmd_show(target_id, store, current_session)
            continue

        if line == "/new":
            current_session = _cmd_new(store, agent)
            continue

        if line.startswith("/"):
            print(f"[!] Unknown command: {line}. Gõ /help để xem list.\n")
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
            print("\n[!] Đã hủy run hiện tại (Ctrl+C). Gõ tiếp hoặc /exit để thoát.", flush=True)
        except Exception as e:
            print(
                f"\n[!] Lỗi khi gọi agent: {type(e).__name__}: {e}",
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
        help="1-shot prompt. Bỏ trống -> mở REPL interactive.",
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=Path.cwd() / ".tap-sessions",
        help="Directory để lưu session (mặc định: ./.tap-sessions trong project)",
    )
    args = parser.parse_args()

    project_root = Path.cwd()
    store = SessionStore(session_dir=args.session_dir)
    current_session = store.new_session()

    agent, harness, plan_state = build_agent_and_harness(
        session=current_session,
        project_root=project_root,
    )

    if args.prompt:
        try:
            exit_code = run_one_shot(harness, args.prompt)
        except Exception as e:
            print(f"[!] Lỗi: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(exit_code)
    else:
        run_repl(agent, harness, store, current_session, plan_state)


if __name__ == "__main__":
    main()
    