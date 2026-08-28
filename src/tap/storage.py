"""Session persistence — JSONL append-only.

Each session is one JSONL file in `session_dir`, named by timestamp:
    ~/.tap/sessions/20260811-152430.jsonl

Each line is one Message serialized via pydantic. Append-only format:
- Write each message as soon as it happens (don't wait for the session to end)
- Crash mid-way → the session still has all messages up to that point
- No complex locking needed since it's one file per session, one writing process

The system prompt and tool definitions are not stored — only the transcript. The
system prompt is rebuilt on resume from the repo's current AGENTS.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from tap.messages import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)


class SessionSummary(BaseModel):
    """Short metadata for one session — shown in /sessions."""
    model_config = ConfigDict(frozen=True)

    id: str
    first_user_message: str  # the first thing the user typed, truncated
    message_count: int
    updated_at: datetime


def _deserialize_message(data: dict) -> Message:
    """Dispatch on the role field because Message is a Union."""
    role = data.get("role")
    if role == "user":
        return UserMessage.model_validate(data)
    if role == "assistant":
        return AssistantMessage.model_validate(data)
    if role == "tool":
        return ToolResultMessage.model_validate(data)
    raise ValueError(f"Unknown message role: {role!r}")


class Session:
    """An open session — messages can be appended to its JSONL file."""

    def __init__(self, path: Path, id: str):
        self._path = path
        self.id = id

    @property
    def path(self) -> Path:
        return self._path

    def append(self, message: Message) -> None:
        """Write one message to the file, flushing immediately so it survives a crash."""
        line = message.model_dump_json()
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class SessionStore:
    """Manages the directory holding session files."""

    def __init__(self, session_dir: Path):
        self._dir = session_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def new_session(self) -> Session:
        """Create a new session whose ID is the current timestamp."""
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self._dir / f"{session_id}.jsonl"
        # Touch the file so it exists even before any message is written
        path.touch()
        return Session(path=path, id=session_id)

    def open_existing(self, session_id: str) -> Session:
        """Reopen a past session to keep appending to the same file."""
        path = self._dir / f"{session_id}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        return Session(path=path, id=session_id)

    def load(self, session_id: str) -> list[Message]:
        """Read all messages of a past session, used by /resume."""
        path = self._dir / f"{session_id}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        messages: list[Message] = []
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    messages.append(_deserialize_message(data))
                except (json.JSONDecodeError, ValueError) as e:
                    # Skip a corrupt line — possibly from a crash mid-write.
                    # Log to stderr if needed; don't raise, since the user wants to resume.
                    print(
                        f"[warn] Skipping malformed line {line_num} in {path.name}: {e}"
                    )
        return messages

    def list_sessions(self) -> list[SessionSummary]:
        """List all past sessions, newest first."""
        summaries: list[SessionSummary] = []
        for path in sorted(self._dir.glob("*.jsonl"), reverse=True):
            session_id = path.stem
            summary = self._summarize(path, session_id)
            if summary is not None:
                summaries.append(summary)
        return summaries

    def _summarize(self, path: Path, session_id: str) -> SessionSummary | None:
        """Skim the file to get the first user message + count."""
        first_user: str = "(empty)"
        count = 0
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    count += 1
                    if first_user == "(empty)":
                        try:
                            data = json.loads(line)
                            if data.get("role") == "user":
                                content = data.get("content", "")
                                # Truncate for brevity
                                first_user = (
                                    content[:60] + "..." if len(content) > 60 else content
                                )
                        except json.JSONDecodeError:
                            continue
        except OSError:
            return None

        updated_at = datetime.fromtimestamp(path.stat().st_mtime)
        return SessionSummary(
            id=session_id,
            first_user_message=first_user,
            message_count=count,
            updated_at=updated_at,
        )
