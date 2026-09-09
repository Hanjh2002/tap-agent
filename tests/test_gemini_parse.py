"""Test GEMINI for the parse response logic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors

from tap.messages import AssistantMessage
from tap.providers import gemini
from tap.providers.gemini import GeminiProvider, GeminiProviderError


def _wrap(parts, finish_reason="STOP"):
    """Build the nested response structure expected by _parse_response.

    _parse_response reads response.candidates[0].content.parts, so the parts
    list must be wrapped in three layers:
    parts -> content -> candidate -> response.
    """
    content = SimpleNamespace(parts=parts)
    candidate = SimpleNamespace(content=content, finish_reason=finish_reason)
    return SimpleNamespace(candidates=[candidate])


# ============================================================================
# TEST: _parse_response extracts thought_signature from the CORRECT part.
#
# Context (verified through a real API call): when GEMINI is thinking and
# calling tool at the same time, the response contains two parts:
#     [0] thought part       -> DO NOT contains signature
#     [1] function_call part -> DOES contains signature

# _parse_response must read the signature from part [1] and attach it to
# the ToolCall.
#
# This test does NOT make a network call. It creates a fake response and passes
# it directly to _parse_response.
# The goal is to lock in this invariant: if a future refactor reads the
# signature from the wrong part or drops it, this test must fail.
# ============================================================================

def test_parse_extracts_signature_from_function_call_part():
    # ---------- Arrange ----------
    # _parse_response accesses these attributes on EVERY part via getattr:
    # part.text / part.thought / part.function_call / part.thought_signature
    # The fake part must define all four attributes, including None values, so
    # that the test accurately represents the real response structure.
    
    signature = b"\x00\xff\xfe-opaque-signature"
    # Arbitrary bytes, intentionally non-UTF-8 to match the real response.

    # Part [0]: thought part — reasoning text, thought=True, NO signature.
    thought_part = SimpleNamespace(
        text="I need to read the file first...",
        thought=True,
        function_call=None,
        thought_signature=None,
    )

    # Part [1]: function_call part — CONTAINS the signature.
    function_call = SimpleNamespace(name="read", args={"path": "README.md"})
    function_call_part = SimpleNamespace(
        text=None,
        thought=False,
        function_call=function_call,
        thought_signature=signature,
        # The signature is stored HERE, matching the real API response.
    )

    fake_response = _wrap([thought_part, function_call_part])

    # _parse_response does not use self._client; it only parses the response.
    # A fake API key is therefore sufficient because the constructor only
    # stores the key and does not make a network call.
    provider = GeminiProvider(api_key="fake-key", model="gemini-2.5-flash")

    # ---------- Act ----------
    result = provider._parse_response(fake_response)

    # ---------- Assert ----------
    assert isinstance(result, AssistantMessage)

    # The thought part is stored in .thinking and must not become a tool call.
    assert result.thinking == "I need to read the file first..."

    # Exactly one tool call must be created from the function_call part.
    assert len(result.tool_calls) == 1

    call = result.tool_calls[0]
    assert call.name == "read"
    assert call.arguments == {"path": "README.md"}

    # Core invariant: the signature must be exactly the bytes provided by the
    # function_call part. Reading the wrong part would produce None and fail.
    assert call.thought_signature == signature

    assert result.stop_reason == "tool_use"


# ============================================================================
# TEST: GEMINI parse for finish_reason
#
# Context: Gemini can end a response with a finish_reason other than "STOP".
# A common example is "MAX_TOKENS", which means the model was cut off before
# completing normally.
#
# In this case, the parser must treat the response as an abnormal termination
# and return an AssistantMessage with stop_reason="error" instead of
# "end_turn".
#
# This test does NOT make a real API call. It creates a fake response with a
# thought-only part and finish_reason="MAX_TOKENS", then passes it directly to
# _parse_response to validate the parser behavior.
#
# The goal is to lock in this invariant: any finish_reason other than "STOP"
# must be treated as an error, so the agent does not continue as if the turn
# ended successfully.
# ============================================================================

def test_gemini_finish_reason_is_not_end_turn():
    thinking_part = SimpleNamespace(
        text="I need to read the file first...",
        thought=True,
        function_call=None,
        thought_signature=None,
    )
    fake_response = _wrap([thinking_part], 
                          finish_reason="MAX_TOKENS")
    provider = GeminiProvider(api_key="fake-key", model="gemini-2.5-flash")
    result = provider._parse_response(fake_response)
    assert result.stop_reason == "error"
    assert result.text == "[Gemini ran out of tokens and stopped the response.]"

def test_gemini_finish_reason_is_government_policy():
    thinking_part = SimpleNamespace(
        text="I need to read the file first...",
        thought=True,
        function_call=None,
        thought_signature=None,
    )
    fake_response = _wrap([thinking_part], 
                          finish_reason="SAFETY")
    provider = GeminiProvider(api_key="fake-key", model="gemini-2.5-flash")
    result = provider._parse_response(fake_response)
    assert result.stop_reason == "error"
    assert result.text == "[Gemini blocked the response due to safety policy.]"


# ============================================================================
# TEST: unknown finish_reason falls back safely.
#
# Gemini may introduce new finish reasons in the future that this client does not
# recognize yet. When that happens, we must not guess at a human-friendly label
# or silently misclassify the result.
#
# The parser should still mark the response as an error, but the text should fall
# back to the raw finish_reason value instead of inventing a description.
# ============================================================================

def test_gemini_unknown_finish_reason_falls_back_to_raw_value():
    thinking_part = SimpleNamespace(
        text="I need to read the file first...",
        thought=True,
        function_call=None,
        thought_signature=None,
    )
    fake_response = _wrap([thinking_part], finish_reason="NEW_REASON")
    provider = GeminiProvider(api_key="fake-key", model="gemini-2.5-flash")

    result = provider._parse_response(fake_response)

    assert result.stop_reason == "error"
    assert result.text == "Gemini finished with finish_reason=NEW_REASON"
