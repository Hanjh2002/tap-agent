"""Test retry logic của GeminiProvider — dùng fake generate_content, không gọi mạng."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors

from tap.messages import AssistantMessage
from tap.providers import gemini
from tap.providers.gemini import GeminiProvider, GeminiProviderError


def _fake_ok_response(text: str = "ok"):
    """Object tối thiểu mà _parse_response đọc được:
    response.candidates[0].content.parts[i].text / .function_call
    """
    part = SimpleNamespace(text=text, function_call=None, thought_signature=None)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidates=[candidate])


class _FakeModels:
    """Giả self._client.models — generate_content ném lỗi n lần rồi thành công."""

    def __init__(self, errors_to_raise: list[Exception], ok_text: str = "ok"):
        self._queue = list(errors_to_raise)
        self._ok_text = ok_text
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self._queue:
            raise self._queue.pop(0)
        return _fake_ok_response(self._ok_text)


def _make_provider(monkeypatch, fake_models: _FakeModels) -> GeminiProvider:
    # requests_per_minute=0 -> _min_interval=0 -> _throttle() no-op (không sleep).
    provider = GeminiProvider(
        api_key="fake-key",
        model="gemini-2.5-flash",
        requests_per_minute=0,
        max_retries=5,
    )
    # Provider chỉ dùng self._client.models.generate_content -> thay cả _client
    # bằng fake namespace là đủ (.models là property read-only, không gán trực tiếp được).
    provider._client = SimpleNamespace(models=fake_models)
    # Tắt backoff sleep để test chạy tức thì.
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    return provider


def test_retries_on_503_then_succeeds(monkeypatch):
    # 503 hai lần, lần ba OK.
    fake = _FakeModels(
        errors_to_raise=[errors.APIError(503, {}), errors.APIError(503, {})],
        ok_text="done",
    )
    provider = _make_provider(monkeypatch, fake)

    result = provider.generate(system="s", messages=[], tools=[])

    assert isinstance(result, AssistantMessage)
    assert result.text == "done"
    assert result.stop_reason == "end_turn"
    # 2 lần fail + 1 lần success = 3 lần gọi -> chứng minh có retry.
    assert fake.calls == 3


def test_gives_up_after_max_retries(monkeypatch):
    # 503 liên tục nhiều hơn max_retries -> cuối cùng phải raise.
    fake = _FakeModels(errors_to_raise=[errors.APIError(503, {})] * 10)
    provider = _make_provider(monkeypatch, fake)

    with pytest.raises(GeminiProviderError):
        provider.generate(system="s", messages=[], tools=[])

    # max_retries=5 -> tổng số lần thử = 5 retry + 1 lần đầu = 6.
    assert fake.calls == 6


def test_non_retryable_400_raises_immediately(monkeypatch):
    # 400 (bad request) KHÔNG nằm trong RETRYABLE_CODES -> raise ngay, không retry.
    fake = _FakeModels(errors_to_raise=[errors.APIError(400, {})] * 10)
    provider = _make_provider(monkeypatch, fake)

    with pytest.raises(GeminiProviderError):
        provider.generate(system="s", messages=[], tools=[])

    # Chỉ gọi đúng 1 lần rồi bỏ cuộc.
    assert fake.calls == 1
    