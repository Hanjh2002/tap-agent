"""Test thought_signature roundtrip trong ToolCall.

Bug đã fix: Gemini 2.5+ yêu cầu thought_signature phải preserve
qua các turn. Test này verify field được lưu và gửi lại đúng.
"""

from __future__ import annotations

from tap.messages import ToolCall


def test_tool_call_default_signature_is_none() -> None:
    """Provider không phải Gemini không dùng signature."""
    call = ToolCall(id="c1", name="read", arguments={"path": "x"})
    assert call.thought_signature is None


def test_tool_call_stores_signature() -> None:
    """Signature là bytes, phải preserve chính xác."""
    sig = b"\x01\x02\x03opaque-signature-bytes"
    call = ToolCall(
        id="c1",
        name="read",
        arguments={"path": "x"},
        thought_signature=sig,
    )
    assert call.thought_signature == sig


def test_tool_call_is_still_frozen_with_new_field() -> None:
    """Field mới không phá tính frozen của ToolCall."""
    import pytest
    from pydantic import ValidationError

    call = ToolCall(id="c1", name="read", arguments={})
    with pytest.raises(ValidationError):
        call.thought_signature = b"changed"

# ---------- Regression: non-UTF-8 signature bytes phải roundtrip qua JSON ----------
#
# Bug v4 gốc: Gemini 2.5-flash trả signature là opaque binary (protobuf), byte value
# tuỳ ý (thường có \x00, \xff, ...). Pydantic default coi bytes = UTF-8 string khi
# serialize JSON → PydanticSerializationError ngay turn đầu có tool_call.
#
# Test cũ ở trên dùng b"\x01\x02\x03opaque-signature-bytes" là UTF-8 hợp lệ nên
# tình cờ không lộ bug. Ta test bằng bytes chắc chắn KHÔNG phải UTF-8.


def test_tool_call_signature_with_non_utf8_bytes_survives_json_roundtrip() -> None:
    """Repro bug prod: signature chứa non-UTF-8 bytes phải serialize + load lại được."""
    import json

    # \xff, \xfe không phải UTF-8 hợp lệ ở đầu chuỗi
    sig = b"\x00\x01\xff\xfe\x80binary-payload"
    call = ToolCall(
        id="c1", name="read", arguments={"path": "x"}, thought_signature=sig
    )

    # 1. model_dump_json không được raise
    line = call.model_dump_json()

    # 2. Sau khi qua JSON, load lại phải bằng signature gốc
    restored = ToolCall.model_validate(json.loads(line))
    assert restored.thought_signature == sig
    assert isinstance(restored.thought_signature, bytes)


def test_assistant_message_with_tool_call_signature_roundtrips_through_jsonl(
    tmp_path,
) -> None:
    """End-to-end: append AssistantMessage có signature → load lại → bằng gốc.

    Đây đúng flow crash ở prod: agent.chat gọi session.append(assistant)
    ngay sau khi provider trả về, và AssistantMessage chứa ToolCall có
    signature bytes.
    """
    from tap.messages import AssistantMessage
    from tap.storage import SessionStore

    sig = b"\xff\xfe\x00\x01protobuf-opaque"
    msg = AssistantMessage(
        tool_calls=(
            ToolCall(
                id="c1",
                name="read",
                arguments={"path": "harness.py"},
                thought_signature=sig,
            ),
        ),
        stop_reason="tool_use",
    )

    store = SessionStore(session_dir=tmp_path)
    session = store.new_session()
    session.append(msg)  # KHÔNG được crash

    loaded = store.load(session.id)
    assert len(loaded) == 1
    assert loaded[0].tool_calls[0].thought_signature == sig
