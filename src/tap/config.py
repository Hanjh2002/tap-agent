"""Config loader — reads from .env or environment variables.

This is the ONLY place that reads `.env`. The Agent doesn't know Settings exists.
The CLI loads Settings, extracts values, and passes them into the Provider/Agent via the constructor.
"""

from __future__ import annotations

from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env or env vars.

    Field name → env var (case-insensitive):
      gemini_api_key      → GEMINI_API_KEY
      tap_model           → TAP_MODEL
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
    tap_max_iterations: int = Field(default=10, ge=1, le=50)
    tap_thinking: Literal["off", "low", "medium", "high", "dynamic"] = "dynamic"


THINKING_BUDGETS: dict[str, int] = {
    "off": 0, "low": 2048, "medium": 8192, "high": 24576, "dynamic": -1,
}


def thinking_budget_from_level(level: str) -> int:
    """Map a level name -> budget int. No match -> dynamic (-1)."""
    return THINKING_BUDGETS.get(level.lower().strip(), -1)
