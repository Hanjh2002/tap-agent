# tap

> A minimal terminal-based coding agent: it reads and edits files, runs shell commands, plans multi-step work on its own, and remembers context across sessions.

tap is a coding agent rebuilt from scratch to understand how these systems actually work under the hood. It's inspired by [tau](https://github.com/huggingface/tau), and deliberately kept small — a clear architecture and a real test suite matter more here than feature count.

**Python 3.12+ · Gemini · 122 tests (no API key required to run them)**

## Features

- **Five tools** — `read`, `bash`, `write`, `edit`, and `update_plan`, which lets the agent break a large task into a checklist and track its own progress.
- **Tunable reasoning** — Gemini's thinking can be set across five levels, with the model's "thought" process shown separately from its answer.
- **Persistent memory** — every session is written to JSONL and can be resumed later.
- **Two modes** — an interactive REPL and a pipe-friendly one-shot mode.
- **Basic safety and network resilience** — access is confined to the project directory, dangerous commands are blocklisted, and transient API failures are retried automatically.

## Design notes

- **`Agent` is a pure loop.** It never touches the SDK, the filesystem, or I/O — everything flows through the generator's `.send()`. That makes the entire control flow testable with a fake provider, offline.
- **The tool hook point is isolated.** Adding confirmation prompts, logging, or a sandbox means wrapping a single executor function; the core stays untouched.
- **`update_plan` rewrites the whole plan on each call** rather than mutating individual steps, so the agent can re-plan mid-task naturally.
- **Providers are a Protocol and tool arguments are validated with pydantic**, so a malformed response from the LLM produces a clean error instead of a crash.

## Quick start

```bash
uv sync
cp .env.example .env                 # add your GEMINI_API_KEY
uv run tap                           # REPL
uv run tap "explain storage.py"      # one-shot
uv run pytest                        # run the tests
```

---

*Architecture referenced from [tau](https://github.com/huggingface/tau) — and, through it, Pi and Claude Code. This is an independent reimplementation built for learning.*