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
