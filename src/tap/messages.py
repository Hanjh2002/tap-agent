"""Transcript message models.

This is the shared data model that every layer knows about. The Provider must
normalize the SDK response into an `AssistantMessage`. The Agent loop mutates
`list[Message]` by reference.

Note: `tool_calls` is a tuple because a frozen model doesn't allow mutable fields.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


class UserMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user"] = "user"
    content: str


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict  # JSON-like, the tool validates it itself via args_mode
    # Gemini 2.5+ specific signature; must be preserved and sent back on the next turn.
    # Other providers (OpenAI, Anthropic) don't need it → default None.
    #
    # NOTE: the signature is opaque binary (protobuf-encoded), with arbitrary byte values.
    # By default Pydantic treats `bytes` as a UTF-8 string when serializing to JSON → it
    # blows up on non-UTF-8 bytes. We base64-encode on the way to JSON and decode on load.
    thought_signature: bytes | None = None

    @field_serializer("thought_signature", when_used="json")
    def _serialize_signature(self, v: bytes | None) -> str | None:
        return b64encode(v).decode("ascii") if v is not None else None

    @field_validator("thought_signature", mode="before")
    @classmethod
    def _deserialize_signature(cls, v: Any) -> bytes | None:
        # Accept both bytes (in-memory) and str (loaded from JSONL).
        if v is None or isinstance(v, bytes):
            return v
        if isinstance(v, str):
            return b64decode(v)
        raise TypeError(
            f"thought_signature phải là bytes | str | None, nhận: {type(v).__name__}"
        )


class AssistantMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["assistant"] = "assistant"
    text: str = ""
    # A summary of the model's reasoning (Gemini thinking). For DISPLAY ONLY —
    # NOT sent back to the model on later turns (_messages_to_contents skips this field).
    # What the model needs to keep its reasoning coherent across turns is the
    # thought_signature on each ToolCall, not this summary text.
    thinking: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: Literal["end_turn", "tool_use", "error"] = "end_turn"


class ToolResultMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["tool"] = "tool"
    tool_call_id: str
    name: str
    content: str
    ok: bool = True


Message = UserMessage | AssistantMessage | ToolResultMessage
