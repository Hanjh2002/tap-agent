"""Gemini provider adapter.

Responsibilities:
1. Convert tap `Message` → Gemini `Content` when build request
2. Convert tap `BaseTool` → Gemini `FunctionDeclaration` (JSON schema)
3. Parse Gemini response → tap `AssistantMessage`
4. Normalize errors

Reference SDK: google-genai (new SDK, not the old google-generativeai).
Docs: https://ai.google.dev/gemini-api/docs/function-calling
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import random
import time

from google import genai
from google.genai import errors,types

from tap.messages import (
    AssistantMessage,
    Message,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

if TYPE_CHECKING:
    from tap.tools.base import BaseTool

class GeminiProviderError(RuntimeError):
    """A normalized Gemini request/response error"""

class GeminiProvider:
    """Provider adapter for Google Gemini."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        requests_per_minute: float = 10.0,
        max_retries: int = 5,
        thinking_budget: int = -1,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_retries = max_retries
        self._thinking_budget = thinking_budget
        self._min_interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._last_call = 0.0

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def generate(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list["BaseTool"],
    ) -> AssistantMessage:
    # Build contents + config ONCE, outside the loop — retries don't rebuild them.
        contents = self._messages_to_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=self._tools_to_gemini(tools) if tools else None,
            thinking_config=self._build_thinking_config(),
        )

        for attempt in range(1, self._max_retries + 2):
            self._throttle()
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                )
                return self._parse_response(response)
            except (errors.APIError, TimeoutError) as exc:
                # Transient errors are worth retrying:
                #  - 429: rate limit
                #  - 500/502/503/504: server-side, usually clears up after a few seconds
                #  - TimeoutError: flaky network
                RETRYABLE_CODES = {429, 500, 502, 503, 504}
                is_transient = (
                    isinstance(exc, TimeoutError)
                    or (isinstance(exc, errors.APIError) and exc.code in RETRYABLE_CODES)
                )
                if is_transient and attempt <= self._max_retries:
                    # Backoff: 1s, 2s, 4s, 8s, 16s + jitter to avoid synchronized retries.
                    delay = (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                    time.sleep(delay)
                    continue
                # Not a 429, or out of retries → normalize and re-raise to the Agent.
                raise GeminiProviderError(f"Gemini request failed: {exc}") from exc

        # Never reached (the loop always returns or raises), but here so the type
        # checker knows every path returns an AssistantMessage or raises.
        raise GeminiProviderError("Max retries exceeded")

    def _build_thinking_config(self) -> "types.ThinkingConfig":
        """budget==0 disables thinking; ==-1 dynamic; >0 caps thinking tokens.
        When enabled, include_thoughts=True to get the reasoning summary for display."""
        if self._thinking_budget == 0:
            return types.ThinkingConfig(include_thoughts=False, thinking_budget=0)
        return types.ThinkingConfig(
            include_thoughts=True,
            thinking_budget=self._thinking_budget,
        )

    # ---------- Request building ----------

    def _messages_to_contents(self, messages: list[Message]) -> list[types.Content]:
        """Convert tap messages → Gemini Content list.

        Mapping:
          UserMessage       → Content(role="user", parts=[Part(text=...)])
          AssistantMessage  → Content(role="model", parts=[Part(text=...) or Part(function_call=...)])
          ToolResultMessage → Content(role="user", parts=[Part(function_response=...)])
        """
        contents: list[types.Content] = []

        for msg in messages:
            if isinstance(msg, UserMessage):
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=msg.content)],
                ))

            elif isinstance(msg, AssistantMessage):
                parts: list[types.Part] = []
                if msg.text:
                    parts.append(types.Part(text=msg.text))
                for call in msg.tool_calls:
                    # Build function_call part
                    # Gemini 2.5+ requires thought_signature to be sent back
                    # together with the function_call, otherwise it raises INVALID_ARGUMENT
                    part_kwargs: dict = {
                        "function_call": types.FunctionCall(
                            name=call.name,
                            args=call.arguments,
                        )
                    }
                    if call.thought_signature is not None:
                        part_kwargs["thought_signature"] = call.thought_signature
                    parts.append(types.Part(**part_kwargs))
                # Gemini requires content to have at least one part
                if not parts:
                    parts.append(types.Part(text=""))
                contents.append(types.Content(role="model", parts=parts))

            elif isinstance(msg, ToolResultMessage):
                # function_response goes back to the model under role="user"
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(
                        function_response=types.FunctionResponse(
                            name=msg.name,
                            response={"content": msg.content, "ok": msg.ok},
                        )
                    )],
                ))

        return contents

    def _tools_to_gemini(self, tools: list["BaseTool"]) -> list[types.Tool]:
        """Convert BaseTool list → Gemini Tool declarations."""
        declarations = []
        for tool in tools:
            declarations.append(types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=_clean_schema_for_gemini(tool.input_schema),
            ))
        return [types.Tool(function_declarations=declarations)]

    # ---------- Response parsing ----------

    def _parse_response(self, response: Any) -> AssistantMessage:
        # Extract text và function_calls từ Gemini response.
        # Defensive: the response may have no candidates if it was blocked
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return AssistantMessage(
                text="[Gemini không trả về candidate nào — có thể bị filter]",
                stop_reason="error",
            )

        content = candidates[0].content
        parts = getattr(content, "parts", None) or []

        text_chunks: list[str] = []
        thought_chunks: list[str] = []
        tool_calls: list[ToolCall] = []

        for i, part in enumerate(parts):
            # part.thought=True -> this is a REASONING summary, not the answer.
            text = getattr(part, "text", None)
            if text:
                if getattr(part, "thought", False):
                    thought_chunks.append(text)
                else:
                    text_chunks.append(text)

            fc = getattr(part, "function_call", None)
            if fc and fc.name:
                args = dict(fc.args) if fc.args else {}
                signature = getattr(part, "thought_signature", None)
                tool_calls.append(ToolCall(
                    id=f"call_{i}_{fc.name}",
                    name=fc.name,
                    arguments=args,
                    thought_signature=signature,
                ))

        return AssistantMessage(
            text="".join(text_chunks),
            thinking="".join(thought_chunks),
            tool_calls=tuple(tool_calls),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )


def _clean_schema_for_gemini(schema: dict) -> dict:
    """Strip JSON Schema fields Gemini doesn't accept + inline $ref.

    Pydantic generates draft JSON Schema with `title`, `$defs`, and for nested
    models it uses `$ref` pointing into `$defs`. Gemini only accepts an OpenAPI 3.0
    subset and does NOT understand $ref → we must resolve it (inline the definition)
    before dropping $defs, otherwise we'd leave $ref pointing at nothing.
    """
    IGNORED_KEYS = {"title", "$defs", "additionalProperties"}
    defs = schema.get("$defs", {})

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            # $ref -> replace with the resolved version from $defs, then keep cleaning.
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = defs.get(ref.split("/")[-1], {})
                return clean(target)
            return {
                k: clean(v)
                for k, v in node.items()
                if k not in IGNORED_KEYS
            }
        if isinstance(node, list):
            return [clean(item) for item in node]
        return node

    return clean(schema)
