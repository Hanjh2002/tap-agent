"""Gemini provider adapter.

Responsibilities:
1. Convert a tap `Message` to Gemini `Content` when building a request.
2. Convert a tap `BaseTool` to a Gemini `FunctionDeclaration` with a JSON schema.
3. Parse a Gemini response into a tap `AssistantMessage`.
4. Normalize errors.

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
    """A normalized Gemini request/response error."""

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
        # Skip throttling if no minimum interval is set (<= 0)
        if self._min_interval <= 0:
            return

        # Calculate seconds elapsed since the last call
        # time.monotonic() is used to stay safe from system clock changes
        elapsed = time.monotonic() - self._last_call

        # Sleep if the elapsed time is less than the minimum interval
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        # Update the timestamp for the current call
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
                    or (isinstance(exc, errors.APIError) 
                        and exc.code in RETRYABLE_CODES)
                )
                if is_transient and attempt <= self._max_retries:
                    # Backoff: 1s, 2s, 4s, 8s, 16s + jitter to avoid synchronized retries.
                    delay = (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                    time.sleep(delay)
                    continue
                # The error is not retryable, or all retries have been exhausted.
                # Normalize it and re-raise it for the Agent.
                raise GeminiProviderError(f"Gemini request failed: {exc}") from exc

        # Never reached (the loop always returns or raises), but here so the type
        # checker knows every path returns an AssistantMessage or raises.
        raise GeminiProviderError("Max retries exceeded")

    def _build_thinking_config(self) -> "types.ThinkingConfig":
        """A budget of 0 disables thinking, -1 enables dynamic thinking, and a positive
        value caps the number of thinking tokens. When thinking is enabled,
        include_thoughts=True requests a reasoning summary for display."""
        if self._thinking_budget == 0:
            return types.ThinkingConfig(include_thoughts=False, thinking_budget=0)
        return types.ThinkingConfig(
            include_thoughts=True,
            thinking_budget=self._thinking_budget,
        )

    # ---------- Request building ----------

    def _messages_to_contents(
            self, messages: list[Message]
        ) -> list[types.Content]:
        """Convert tap messages → list of Gemini Content objects.

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
                    # Build the function_call part
                    # Gemini 2.5+ requires thought_signature to be sent back together with the
                    # function_call; otherwise, it raises INVALID_ARGUMENT.
                    part_kwargs: dict = {
                        "function_call": types.FunctionCall(
                            name=call.name,
                            args=call.arguments,
                        )
                    }
                    if call.thought_signature is not None:
                        part_kwargs["thought_signature"] = call.thought_signature
                    parts.append(types.Part(**part_kwargs))

                # Gemini requires each content object to contain at least one part
                if not parts:
                    parts.append(types.Part(text=""))
                contents.append(types.Content(role="model", parts=parts))

            elif isinstance(msg, ToolResultMessage):
                # Send the function response back to the model with role="user"
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
        # Extract text and function_calls from Gemini response.
        # Defensive: the response may have no candidates if it was blocked
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return AssistantMessage(
                text="[Gemini returned no candidates; the response may have been blocked by a safety filter]",
                stop_reason="error",
            )

        # If finish_reason is not STOP, it's an error.
        finish_reason = getattr(candidates[0], "finish_reason", None)
        if finish_reason is not None and finish_reason != "STOP":
            description = self._describe_finish_reason(finish_reason)
            return AssistantMessage(
                text=description or f"Gemini finished with finish_reason={finish_reason}",
                stop_reason="error",
            )

        content = candidates[0].content
        parts = getattr(content, "parts", None) or []

        text_chunks: list[str] = []
        thought_chunks: list[str] = []
        tool_calls: list[ToolCall] = []

        for i, part in enumerate(parts):
            # part.thought=True -> this is a REASONING summary, not the final answer.
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

    # ---------- Finish-reason Handling ----------
    def _describe_finish_reason(self, finish_reason: str | types.FinishReason) -> str | None:
        """Return a human-readable description for a Gemini finish reason.

        Gemini occasionally adds new finish reasons over time. We do not want to
        guess or fabricate descriptions for unknown values, because that can hide
        real lifecycle changes and make debugging harder.

        For known reasons we return a friendly message. For unrecognized values we
        fall back to None so the caller can decide whether to ignore, log, or
        surface the raw reason without imposing assumptions.
        """
        fr_name = getattr(finish_reason, "name", finish_reason)

        known = {
            "SAFETY": "[Gemini blocked the response due to safety policy.]",
            "RECITATION": "[Gemini blocked the response due to recitation policy.]",
            "PROHIBITED_CONTENT": "[Gemini blocked the response due to prohibited content.]",
            "SPII": "[Gemini blocked the response due to sensitive personal information.]",
            "BLOCKLIST": "[Gemini blocked the response due to a blocklist match.]",
            "MAX_TOKENS": "[Gemini ran out of tokens and stopped the response.]",
        }

        if fr_name in known:
            return known[fr_name]

        # Fallback for future Gemini values we do not recognize yet.
        # Returning None keeps the caller honest instead of inventing a message.
        return None
        

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
