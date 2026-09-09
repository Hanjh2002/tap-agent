"""Configuration loader for `.env` files and environment variables.

This is the only module that reads `.env`. The Agent does not know about
Settings. The CLI loads the settings and passes the required values to the
Provider/Agent through their constructors.
"""

from __future__ import annotations

from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env or environment variables.

    Field name → env var (case-insensitive):
      gemini_api_key      → GEMINI_API_KEY
      tap_model           → TAP_MODEL
      tap_language        → TAP_LANGUAGE
      tap_max_iterations  → TAP_MAX_ITERATIONS
      tap_thinking        → TAP_THINKING
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = Field(
        ...,
        description="Gemini API key. Lấy tại https://aistudio.google.com/apikey",
    )
    tap_model: str = Field(default="gemini-2.5-flash")
    tap_language: Literal["auto", "vi", "en", "ja", "ko"] = "auto"
    tap_ui_language: Literal["en", "vi"] = "en"
    tap_max_iterations: int = Field(default=10, ge=1, le=50)
    tap_thinking: Literal["off", "low", "medium", "high", "dynamic"] = "dynamic"


THINKING_BUDGETS: dict[str, int] = {
    "off": 0, "low": 2048, "medium": 8192, "high": 24576, "dynamic": -1,
}


def thinking_budget_from_level(level: str) -> int:
    """Return the thinking-token budget for a level.
    Unknown levels fall back to dynamic mode, represented by -1.
    """
    return THINKING_BUDGETS.get(level.lower().strip(), -1)
