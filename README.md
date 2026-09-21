# tap

> A minimal terminal-based coding agent: it reads and edits files, runs shell commands, plans multi-step work on its own, loads skills on demand, and remembers context across sessions.

tap is a coding agent rebuilt from scratch to understand how these systems actually work under the hood. It's inspired by [tau](https://github.com/huggingface/tau), and deliberately kept small — a clear architecture and a real test suite matter more here than feature count.

**Python 3.12+ · Gemini · 158 tests (no API key required to run them)**

## Features

- **Five tools** — `read`, `write`, `edit`, `bash`, and `update_plan`, which lets the agent break a large task into a checklist and track its own progress.
- **Line-range paging for `read`** — `offset`/`limit` let the agent page through large files instead of dumping the whole thing; oversize single lines are truncated safely instead of blowing the context budget.
- **Atomic multi-edit for `edit`** — a single call can carry several `old`/`new` replacements; every one is validated (unique match, no overlaps, no no-ops) against the original content before anything is written, so a bad replacement never leaves a file half-patched.
- **Skills (progressive disclosure)** — drop a `SKILL.md` under `.agents/skills/` or `.tap/skills/` (project or user-level) and its name + description are injected into the system prompt as an index; the agent reads the full file with the `read` tool only when a task actually matches it.
- **Project context via `AGENTS.md`** — if present at the project root, its contents are injected into the system prompt automatically.
- **Tunable reasoning** — Gemini's thinking can be set across five levels (`off`/`low`/`medium`/`high`/`dynamic`), with the model's "thought" process shown separately (and dimmed) from its answer.
- **Configurable reply language** — force replies into a specific language (`vi`/`en`/`ja`/`ko`) or leave it on `auto` to mirror whatever language the user writes in.
- **Persistent memory** — every session is written to JSONL as it happens (crash-safe, append-only) and can be listed, reviewed, or resumed later via slash commands.
- **Two modes** — an interactive REPL with slash commands, and a pipe-friendly one-shot mode (`tap "prompt"`) for scripting.
- **Basic safety and network resilience** — filesystem access is confined to the project directory (plus configured skill roots for `read` only), a blocklist rejects obviously destructive shell commands, and transient Gemini API failures are retried with backoff.

## Slash commands (REPL mode)

| Command | Description |
|---|---|
| `/help` | Show the command list |
| `/plan` | View the current plan (from `update_plan`) |
| `/clear` | Reset the current session's transcript (the file itself isn't deleted) |
| `/sessions` | List saved sessions |
| `/show [id]` | Review a session's content (defaults to the current one) |
| `/resume <id>` | Load a past session and keep chatting in it |
| `/new` | End the current session and start a new one |
| `/exit`, `/quit` | Exit tap |

## Design notes

- **`Agent` is a pure loop.** It never touches the SDK, the filesystem, or I/O — everything flows through the generator's `.send()`. That makes the entire control flow testable with a fake provider, offline.
- **The tool hook point is isolated.** `AgentHarness` drives the Agent generator and calls a single `tool_executor` function; adding confirmation prompts, logging, or a sandbox means wrapping that one function, the core stays untouched.
- **`update_plan` rewrites the whole plan on each call** rather than mutating individual steps, so the agent can re-plan mid-task naturally.
- **Providers are a Protocol and tool arguments are validated with pydantic**, so a malformed response from the LLM produces a clean error instead of a crash.
- **Path safety is centralized.** Every filesystem tool resolves paths through one helper that rejects anything outside the allowed roots — `write`/`edit`/`bash` are locked to the project directory; `read` is additionally allowed inside configured skill roots, on the principle of least privilege.
- **Interrupting a turn never corrupts the transcript.** If a run is cancelled mid-tool-call (Ctrl+C), any tool call left without a matching result is patched with a synthetic "cancelled" result before the next turn starts, so the next provider request stays valid.

## Quick start

```bash
uv sync
cp .env.example .env                 # add your GEMINI_API_KEY
uv run tap                           # REPL
uv run tap "explain storage.py"      # one-shot
uv run pytest                        # run the tests
```

## Configuration

All settings are read from `.env` (or real environment variables) via `Settings` in [config.py](src/tap/config.py). See [.env.example](.env.example) for the full list with defaults:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Gemini API key — get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `TAP_MODEL` | `gemini-2.5-flash` | Gemini model to use |
| `TAP_UI_LANGUAGE` | `en` | CLI interface language: `en` \| `vi` |
| `TAP_LANGUAGE` | `auto` | Agent reply language: `auto` \| `vi` \| `en` \| `ja` \| `ko` |
| `TAP_MAX_ITERATIONS` | `10` | Max tool-call loop iterations per turn (1–50) |
| `TAP_THINKING` | `dynamic` | Gemini thinking level: `off` \| `low` \| `medium` \| `high` \| `dynamic` |

If `GEMINI_API_KEY` (or `TAP_MODEL`/`TAP_LANGUAGE`/`TAP_UI_LANGUAGE`) is missing, the CLI prompts for it interactively on first run instead of failing outright.

---

*Architecture referenced from [tau](https://github.com/huggingface/tau) — and, through it, Pi and Claude Code. This is an independent reimplementation built for learning.*
