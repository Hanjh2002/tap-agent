"""Bash tool — runs shell commands inside project_root.

v2:
- Runs in project_root (not the Python process's cwd)
- Blocklists clearly dangerous commands (rm -rf, sudo, format, ...)
- Blocklistis is substring-based; it won't false-negative on `bash -c` wrapping
  (the LLM could still slip past via echo pipes, base64, ... — the blocklist is a basic
  safety net, not a real sandbox)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from tap.tools.base import BaseTool, ToolResult


# Dangerous phrases — checked case-insensitively
# Not aiming to be exhaustive, just blocking the most common ones
_DANGEROUS_PATTERNS: tuple[str, ...] = (
    # Unix destructive
    "rm -rf",
    "rm -fr",
    "rm -r ",
    "sudo ",
    "chmod -r ",
    "mkfs",
    "dd if=",
    "> /dev/",
    "shred ",
    ":(){:|:&};:",  # fork bomb
    # Windows destructive
    "del /",
    "rd /s",
    "rmdir /s",
    "format ",
    "shutdown",
    "taskkill",
    "reg delete",
    "cipher /w",
    "diskpart",
)


def _is_dangerous(command: str) -> bool:
    """Return True if the command contains a blocklisted phrase."""
    lower = command.lower()
    return any(pattern in lower for pattern in _DANGEROUS_PATTERNS)


class BashArgs(BaseModel):
    command: str = Field(..., description="Shell command to run")
    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout in seconds (1-300, default 30)",
    )


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Run a shell command inside the project directory and return exit code, stdout, stderr. "
        "Use for file listings (ls, find), searches (grep, rg), running scripts, "
        "checking versions, or any command-line task. Times out after 30 seconds by default. "
        "Dangerous commands (rm -rf, sudo, format, shutdown, ...) are blocked for safety."
    )
    args_model = BashArgs

    MAX_OUTPUT = 50_000

    def __init__(self, project_root: Path):
        self._project_root = project_root

    def _run(self, args: BashArgs) -> ToolResult:
        if _is_dangerous(args.command):
            return ToolResult(
                output=(
                    f"Command blocked for safety: '{args.command}'. "
                    "Dangerous operations (rm -rf, sudo, format, shutdown, ...) "
                    "are not allowed. If you need to remove files, ask the user "
                    "to do it manually."
                ),
                ok=False,
            )

        try:
            proc = subprocess.run(
                args.command,
                shell=True,
                capture_output=True,
                # Do NOT force utf-8: Windows command output uses the system codepage
                # (cp1252/cp850); forcing utf-8 would mangle non-ASCII chars (à -> �).
                # text=True -> use the OS's default encoding (correct for most
                # platform output). errors="replace" -> unknown bytes become '�' instead
                # of crashing the reader thread (a cp1252 bug on Windows).
                text=True,
                errors="replace",
                timeout=args.timeout,
                cwd=str(self._project_root),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                output=f"Command timed out after {args.timeout}s: {args.command}",
                ok=False,
            )
        except Exception as e:
            return ToolResult(
                output=f"Failed to execute command: {type(e).__name__}: {e}",
                ok=False,
            )

        output = (
            f"exit_code: {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}"
            f"--- stderr ---\n{proc.stderr}"
        )

        if len(output) > self.MAX_OUTPUT:
            output = output[: self.MAX_OUTPUT] + "\n\n[truncated]"

        return ToolResult(
            output=output,
            ok=(proc.returncode == 0),
        )
    