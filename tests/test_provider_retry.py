"""Test GeminiProvider retry logic using a fake generate_content method;
does not make network calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors

from tap.messages import AssistantMessage
from tap.providers import gemini
from tap.providers.gemini import GeminiProvider, GeminiProviderError


def _fake_ok_response(text: str = "ok"):
    """Minimal object read by _parse_response:
    response.candidates[0].content.parts[i].text / .function_call"""
    part = SimpleNamespace(text=text, function_call=None, thought_signature=None)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidates=[candidate])


class _FakeModels:
    """Mock self._client.models — generate_content raises errors several
    times and then succeeds."""

    def __init__(self, 
                 errors_to_raise: list[Exception], 
                 ok_text: str = "ok"):
        self._queue = list(errors_to_raise)
        self._ok_text = ok_text
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self._queue:
            raise self._queue.pop(0)
        return _fake_ok_response(self._ok_text)


def _make_provider(monkeypatch, fake_models: _FakeModels) -> GeminiProvider:
    # requests_per_minute=0 -> _min_interval=0 -> _throttle() no-op (does not sleep).
    provider = GeminiProvider(
        api_key="fake-key",
        model="gemini-2.5-flash",
        requests_per_minute=0,
        max_retries=5,
    )
    # Provider only uses self._client.models.generate_content, so replacing
    # the entire _client with a fake namespace is sufficient (.models is a
    # read-only property and cannot be assigned directly).
    provider._client = SimpleNamespace(models=fake_models)
    # Disable backoff sleeping so the test runs immediately.
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    return provider


def test_retries_on_503_then_succeeds(monkeypatch):
    # 503 twice, then OK.
    fake = _FakeModels(
        errors_to_raise=[errors.APIError(503, {}), 
                         errors.APIError(503, {})],
        ok_text="done",
    )
    provider = _make_provider(monkeypatch, fake)

    result = provider.generate(system="s", messages=[], tools=[])

    assert isinstance(result, AssistantMessage)
    assert result.text == "done"
    assert result.stop_reason == "end_turn"
    # 2 failures + 1 success = 3 calls, proving that retry works.
    assert fake.calls == 3


def test_gives_up_after_max_retries(monkeypatch):
    # Continuous 503 errors exceeding max_retries -> eventually raises.
    fake = _FakeModels(errors_to_raise=[errors.APIError(503, {})] * 10)
    provider = _make_provider(monkeypatch, fake)

    with pytest.raises(GeminiProviderError):
        provider.generate(system="s", messages=[], tools=[])

    # max_retries=5 -> 5 retries + 1 initial attempt = 6 total attempts.
    assert fake.calls == 6


def test_non_retryable_400_raises_immediately(monkeypatch):
    # 400 (bad request) is NOT included in RETRYABLE_CODES -> raises immediately
    # without retrying.
    fake = _FakeModels(errors_to_raise=[errors.APIError(400, {})] * 10)
    provider = _make_provider(monkeypatch, fake)

    with pytest.raises(GeminiProviderError):
        provider.generate(system="s", messages=[], tools=[])

   # Only one call is made before giving up.
    assert fake.calls == 1

# ============================================================================
# TEST: _parse_response extracts thought_signature into the CORRECT part.
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

def _wrap(parts):
    """Build the nested response structure expected by _parse_response.

    _parse_response reads response.candidates[0].content.parts, so the parts
    list must be wrapped in three layers:
    parts -> content -> candidate -> response.
    """
    content = SimpleNamespace(parts=parts)
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidate=[candidate])


# it directly to _parse_response.
# The goal is to lock in this invariant: if a future refactor reads the
# signature from the wrong part or drops it, this test must fail.
# ============================================================================

def _wrap(parts):
    """Build the nested response structure expected by _parse_response.

    _parse_response reads response.candidates[0].content.parts, so the parts
    list must be wrapped in three layers:
    parts -> content -> candidate -> response.
    """
    content = SimpleNamespace(parts=parts)
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidates=[candidate])


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
