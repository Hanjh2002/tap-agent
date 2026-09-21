"""Test Settings — verify loading from environment variables."""

from __future__ import annotations

import pytest

from tap.config import Settings

def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings loads from dummy environment variables, not .env file."""
    # Override environment variables
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-api-key")
    monkeypatch.setenv("TAP_MODEL", "gemini-dummy-model")
    monkeypatch.setenv("TAP_LANGUAGE", "auto")
    monkeypatch.setenv("TAP_UI_LANGUAGE", "vi")
    monkeypatch.setenv("TAP_MAX_ITERATIONS", "5")
    monkeypatch.setenv("TAP_THINKING", "off")

    # Re-initialize Settings to pick up the new environment variables
    # Pydantic's BaseSettings might cache, but for testing it should be fine
    # if we force a fresh load.
    settings = Settings()
    
    assert settings.gemini_api_key == "dummy-api-key"
    assert settings.tap_model == "gemini-dummy-model"
    assert settings.tap_language == "auto"
    assert settings.tap_ui_language == "vi"
    assert settings.tap_max_iterations == 5
    assert settings.tap_thinking == "off"
