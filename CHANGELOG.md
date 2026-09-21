# Changelog

All notable changes to `tap` are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.0] 

### Added
- **`read`: offset/limit line-range paging.** `ReadArgs` gained `offset` (1-indexed start line) and `limit` (max lines), so the agent can page through large files instead of dumping the whole thing in one call. A per-call character cap (`MAX_CHARS = 50_000`) still applies on top of the line limit; a single line that alone exceeds the cap is truncated (`oversize` state) instead of being skipped or crashing. Output is annotated with metadata (`[offset=…, remaining=… — path]`) so the model knows whether to keep paging. *(56a2654)*
- **`edit`: atomic multi-edit with all-or-nothing validation.** `EditArgs.edits` is now a list — one call can carry several `old`/`new` replacements. Every replacement is validated against the *original* file content before anything is written: each `old` must match exactly once (`not_found`/`ambiguous`), overlapping replacement spans are rejected (`overlap`), and no-op or empty replacements are rejected (`no_operation`/`empty_old`). If any edit is invalid, nothing is written — no partial patch. *(e0c33b7)*

### Fixed
- **Interrupting a turn (Ctrl+C) no longer corrupts the next request.** If a run is cancelled after an assistant message with `tool_calls` was appended but before all results came back, `Agent.cancel_pending_tool_calls()` now synthesizes a `ToolResult(ok=False, content="cancelled by user")` for every orphaned call. Without this, an unresolved `function_call` would make the *next* Gemini request fail with `INVALID_ARGUMENT`. `AgentHarness.chat()` calls this cleanup in a `finally` block covering both normal completion and interruption. *(c86c263)*

### Internal
- Test files reorganized for clarity: `test_write_edit.py` split into `test_write_tool.py` + `test_edit_tool.py`; `test_read_bash.py` renamed to `test_bash_tool.py`. Added `tests/conftest.py` with a shared `assert_no_orphaned_tool_calls` fixture.
- Test suite grew from 122 to 158 tests.

## [0.3.0] 

### Added
- **Configurable agent reply language (`TAP_LANGUAGE`).** New setting: `auto` (mirror the user's language, default) or a forced code (`vi`/`en`/`ja`/`ko`). Implemented as a language directive appended to the system prompt in `build_system_prompt()`. *(2b263d5)*
- **CLI UI language (`TAP_UI_LANGUAGE`).** All CLI-facing strings (prompts, `/help`, error messages) were extracted into an `en`/`vi` string table (`UI_TEXT` in `cli.py`) with a `ui_text()` lookup helper. On first run with neither `--ui-language` nor `TAP_UI_LANGUAGE` set, the CLI now interactively asks the user to pick English or Vietnamese, and separately asks which reply-language mode the agent should use. *(7770ce8)*
- `--ui-language {en,vi}` CLI flag to set the interface language non-interactively.

### Fixed
- **Gemini provider no longer silently treats a blocked/truncated response as success.** `_parse_response()` now checks `finish_reason`: anything other than `STOP` (`SAFETY`, `RECITATION`, `PROHIBITED_CONTENT`, `SPII`, `BLOCKLIST`, `MAX_TOKENS`, or an unrecognized future value) is surfaced as `stop_reason="error"` with a human-readable message instead of being ignored. *(2342cf9)*
- Hardened `thought_signature` extraction/round-tripping in `_parse_response()` and `_messages_to_contents()` (the opaque, per-tool-call signature Gemini 2.5+ requires to be echoed back on the next turn), with much stronger regression coverage in `test_provider_retry.py`. *(0df6a9f)*
- `config.py`: corrected the `tap_ui_language`/`tap_language` field mapping/ordering so both settings resolve from the right environment variables. *(d1656cd)*

## [0.2.0] 

Initial recorded baseline (first commit into this repository) — the full "v4" architecture already in place:
- `Agent` as a pure generator-based loop decoupled from I/O; `AgentHarness` executing tools via a swappable `tool_executor`.
- Five tools: `read`, `write`, `edit`, `bash`, `update_plan`, all path-safety-checked through `tools/_paths.py`.
- Skills system (`SKILL.md` discovery + progressive disclosure) and `AGENTS.md` project-context injection.
- JSONL session persistence (`storage.py`) with resume/list/show support.
- Gemini provider with retry/backoff, rate limiting, and tunable thinking budgets.

---

*Versions correspond to `pyproject.toml`. Dates are commit dates, not necessarily publish/tag dates.*
