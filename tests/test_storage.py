"""Test SessionStore + Session — JSONL persistence."""

from __future__ import annotations

import time
from pathlib import Path

from tap.messages import AssistantMessage, ToolCall, ToolResultMessage, UserMessage
from tap.storage import SessionStore


def test_new_session_creates_file(tmp_path: Path) -> None:
    store = SessionStore(session_dir=tmp_path)
    session = store.new_session()

    assert session.path.exists()
    assert session.path.suffix == ".jsonl"
    assert session.id == session.path.stem


def test_session_append_writes_line_per_message(tmp_path: Path) -> None:
    store = SessionStore(session_dir=tmp_path)
    session = store.new_session()

    session.append(UserMessage(content="hello"))
    session.append(AssistantMessage(text="hi", stop_reason="end_turn"))

    lines = session.path.read_text().strip().split("\n")
    assert len(lines) == 2


def test_load_roundtrip_preserves_messages(tmp_path: Path) -> None:
    """Serialize + deserialize phải preserve nội dung."""
    store = SessionStore(session_dir=tmp_path)
    session = store.new_session()

    session.append(UserMessage(content="hello"))
    session.append(AssistantMessage(
        text="Let me check",
        tool_calls=(ToolCall(id="c1", name="read", arguments={"path": "x.txt"}),),
        stop_reason="tool_use",
    ))
    session.append(ToolResultMessage(
        tool_call_id="c1",
        name="read",
        content="file content",
        ok=True,
    ))
    session.append(AssistantMessage(text="Done", stop_reason="end_turn"))

    loaded = store.load(session.id)

    assert len(loaded) == 4
    assert loaded[0].role == "user"
    assert loaded[0].content == "hello"
    assert loaded[1].role == "assistant"
    assert loaded[1].tool_calls[0].name == "read"
    assert loaded[1].tool_calls[0].arguments == {"path": "x.txt"}
    assert loaded[2].role == "tool"
    assert loaded[2].ok is True
    assert loaded[3].text == "Done"


def test_load_skips_malformed_lines(tmp_path: Path, capsys) -> None:
    """Line hỏng (crash giữa write) không được crash load."""
    store = SessionStore(session_dir=tmp_path)
    session = store.new_session()

    session.append(UserMessage(content="ok"))
    # Ghi thêm 1 line hỏng
    with session.path.open("a") as f:
        f.write('{"broken": json\n')  # invalid JSON
    session.append(UserMessage(content="also ok"))

    loaded = store.load(session.id)
    assert len(loaded) == 2  # bỏ qua line hỏng
    assert loaded[0].content == "ok"
    assert loaded[1].content == "also ok"


def test_list_sessions_shows_newest_first(tmp_path: Path) -> None:
    store = SessionStore(session_dir=tmp_path)

    s1 = store.new_session()
    s1.append(UserMessage(content="first session"))
    time.sleep(1.1)  # đảm bảo timestamp id khác nhau
    s2 = store.new_session()
    s2.append(UserMessage(content="second session"))

    summaries = store.list_sessions()
    assert len(summaries) == 2
    # Newest first
    assert summaries[0].id == s2.id
    assert summaries[1].id == s1.id


def test_list_sessions_shows_first_user_message(tmp_path: Path) -> None:
    store = SessionStore(session_dir=tmp_path)
    session = store.new_session()
    session.append(UserMessage(content="how do I use async"))
    session.append(AssistantMessage(text="here's how", stop_reason="end_turn"))

    summaries = store.list_sessions()
    assert summaries[0].first_user_message == "how do I use async"
    assert summaries[0].message_count == 2


def test_open_existing_appends_to_same_file(tmp_path: Path) -> None:
    """/resume phải append vào file cũ, không tạo file mới."""
    store = SessionStore(session_dir=tmp_path)
    session = store.new_session()
    session.append(UserMessage(content="original"))

    reopened = store.open_existing(session.id)
    reopened.append(UserMessage(content="continuation"))

    loaded = store.load(session.id)
    assert len(loaded) == 2
    assert loaded[0].content == "original"
    assert loaded[1].content == "continuation"


def test_load_nonexistent_session_raises(tmp_path: Path) -> None:
    store = SessionStore(session_dir=tmp_path)
    try:
        store.load("nonexistent-id")
    except FileNotFoundError:
        return
    raise AssertionError("Expected FileNotFoundError")
