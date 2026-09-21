"""Test for read & bash tools.

Tools ONLY recieve project_root and reject path traversal + dangerous cmd.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tap.tools.bash import BashTool
from tap.tools.read import ReadTool


def test_bash_runs_simple_command(tmp_path: Path) -> None:
    result = BashTool(project_root=tmp_path).execute({"command": "echo hello"})

    assert result.ok is True
    assert "hello" in result.output
    assert "exit_code: 0" in result.output


def test_bash_reports_nonzero_exit_code(tmp_path: Path) -> None:
    result = BashTool(project_root=tmp_path).execute({"command": "exit 42"})

    assert result.ok is False
    assert "exit_code: 42" in result.output


def test_bash_timeout(tmp_path: Path) -> None:
    # Python có sẵn trên mọi platform, dùng thay sleep
    cmd = f'{sys.executable} -c "import time; time.sleep(5)"'
    result = BashTool(project_root=tmp_path).execute({"command": cmd, "timeout": 1})

    assert result.ok is False
    assert "timed out" in result.output.lower()


def test_bash_missing_command_returns_validation_error(tmp_path: Path) -> None:
    result = BashTool(project_root=tmp_path).execute({})

    assert result.ok is False


def test_bash_blocks_rm_rf(tmp_path: Path) -> None:
    """v4: dangerous command blocklist."""
    result = BashTool(project_root=tmp_path).execute({"command": "rm -rf /"})

    assert result.ok is False
    assert "blocked for safety" in result.output.lower()


def test_bash_blocks_sudo(tmp_path: Path) -> None:
    result = BashTool(project_root=tmp_path).execute({"command": "sudo cat /etc/shadow"})

    assert result.ok is False
    assert "blocked for safety" in result.output.lower()


def test_bash_blocks_case_insensitive(tmp_path: Path) -> None:
    """Blocklist phải case-insensitive."""
    result = BashTool(project_root=tmp_path).execute({"command": "RM -RF /"})

    assert result.ok is False


def test_bash_runs_in_project_root(tmp_path: Path) -> None:
    """Command phải chạy với cwd = project_root."""
    # Dùng Python thay pwd để cross-platform
    cmd = f'{sys.executable} -c "import os; print(os.getcwd())"'
    result = BashTool(project_root=tmp_path).execute({"command": cmd})

    assert result.ok is True
    assert str(tmp_path.resolve()) in result.output or str(tmp_path) in result.output


# ---------- input_schema ----------

def test_bash_input_schema_has_command_field(tmp_path: Path) -> None:
    schema = BashTool(project_root=tmp_path).input_schema

    assert "command" in schema["properties"]
    assert "timeout" in schema["properties"]
    assert schema["required"] == ["command"]
