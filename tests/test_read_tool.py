"""Test the ReadTool's file access, validation, pagination, and truncation behavior."""


from __future__ import annotations

import sys
from pathlib import Path

from tap.tools.read import ReadTool


def test_read_returns_file_content(tmp_path: Path) -> None:
    file = tmp_path / "hello.txt"
    file.write_text("hello world", encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute({"path": "hello.txt"})

    assert result.ok is True
    assert "hello world" in result.output


def test_read_missing_file_returns_error(tmp_path: Path) -> None:
    result = ReadTool(project_root=tmp_path).execute({"path": "nonexistent.txt"})

    assert result.ok is False
    assert "not found" in result.output.lower()


def test_read_directory_returns_error(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    result = ReadTool(project_root=tmp_path).execute({"path": "subdir"})

    assert result.ok is False
    assert "directory" in result.output.lower()


def test_read_denies_path_traversal(tmp_path: Path) -> None:
    """LLM can NOT read files from project_root."""
    result = ReadTool(project_root=tmp_path).execute({"path": "../../etc/passwd"})

    assert result.ok is False
    assert "outside" in result.output.lower()


def test_read_missing_path_arg_returns_validation_error(tmp_path: Path) -> None:
    result = ReadTool(project_root=tmp_path).execute({})

    assert result.ok is False
    assert "invalid arguments" in result.output.lower()


def test_read_wrong_type_arg_returns_validation_error(tmp_path: Path) -> None:
    result = ReadTool(project_root=tmp_path).execute({"path": 12345})

    assert result.ok is False


def test_read_truncates_long_file(tmp_path: Path) -> None:
    file = tmp_path / "big.txt"
    file.write_text("x" * 100_000, encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute({"path": "big.txt"})

    assert result.ok is True
    assert "truncated" in result.output
    assert len(result.output) < 60_000

# ---------- input_schema ----------

def test_read_input_schema_has_path_field(tmp_path: Path) -> None:
    schema = ReadTool(project_root=tmp_path).input_schema

    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "path" in schema["required"]


# --------- test with offset & limit ----------
# default: offset = 1, limit = 2000, MAX_CHARS = 50000

def test_read_offset_limit_returns_exact_line_range(tmp_path: Path) -> None:
    file = tmp_path / "hello.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    file.write_text(content, encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute(
        {"path": "hello.txt", "offset": 50, "limit": 10}
    )

    # Keep only real file lines; 
    # and ignore metadata lines such as "[truncated]" or other bracketed markers.
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert len(returned) == 10

    assert "L50" in returned
    assert "L59" in returned
    assert "L49" not in returned
    assert "L60" not in returned

def test_read_offset_is_one_indexed(tmp_path: Path) -> None:
    file = tmp_path / "hello.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    file.write_text(content, encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute(
        {"path": "hello.txt", "offset": 1, "limit": 1}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]
    assert result.ok is True
    assert "L1" in returned
    assert "L2" not in returned

def test_read_limit_beyond_end_stops_at_last_line(tmp_path: Path) -> None:
    file = tmp_path / "hello.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    file.write_text(content, encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute(
        {"path": "hello.txt", "offset": 95, "limit": 10}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert len(returned) == 6
    assert "L94" not in returned
    assert "L95" in returned
    assert "L96" in returned
    assert "L97" in returned
    assert "L98" in returned
    assert "L99" in returned
    assert "L100" in returned

def test_read_short_file_without_args_returns_all_lines(tmp_path: Path) -> None:
    file = tmp_path / "short.txt"
    short_text = "\n".join(f"L{i}" for i in range(1, 31))
    file.write_text(short_text, encoding="utf-8")
    result = ReadTool(project_root=tmp_path).execute({"path": "short.txt"})
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert len(returned) == 30
    assert "L1" in returned
    assert "L30" in returned

def test_read_long_file_without_limit_caps_at_default(tmp_path: Path) -> None:
    file = tmp_path / "long.txt"
    long_text = "\n".join(f"L{i}" for i in range(1, 2501))
    file.write_text(long_text, encoding="utf-8")
    result = ReadTool(project_root=tmp_path).execute({"path": "long.txt"})
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert len(returned) == 2000
    assert "L1" in returned
    assert "L2000" in returned
    assert "L2001" not in returned
    assert "offset=2001" in result.output
    assert "remaining=500" in result.output

def test_read_offset_past_end_is_ok_with_line_count(tmp_path: Path) -> None:
    file = tmp_path / "hello.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    file.write_text(content, encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute(
        {"path": "hello.txt", "offset": 150}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert len(returned) == 0
    assert "offset=150" in result.output
    assert "file_len=100" in result.output

def test_read_offset_just_past_last_line_is_ok(tmp_path: Path) -> None:
    file = tmp_path / "hello.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    file.write_text(content, encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute(
        {"path": "hello.txt", "offset": 101}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert len(returned) == 0
    assert "offset=101" in result.output
    assert "file_len=100" in result.output

def test_read_empty_file_reports_no_lines(tmp_path: Path) -> None:
    file = tmp_path / "empty.txt"
    file.write_text("", encoding="utf-8")

    result = ReadTool(project_root=tmp_path).execute({"path": "empty.txt"})
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert len(file.read_text(encoding="utf-8")) == 0
    assert len(returned) == 0
    assert "[File is empty!]" in result.output

def test_read_char_cap_cuts_on_line_boundary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ReadTool, "MAX_CHARS", 100 )
    file = tmp_path / "chars_cut.txt"
    content = "\n".join(f"L{i}" + " x" * 5 for i in range(1, 101))
    original = content.splitlines()
    file.write_text(content, encoding="utf-8")
    result = ReadTool(project_root=tmp_path).execute(
        {"path": "chars_cut.txt"}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert returned[-1] in original
    assert original[0] in returned

def test_read_char_cap_reports_last_full_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ReadTool, "MAX_CHARS", 40)
    file = tmp_path / "last_full_line.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    original = content.splitlines()
    file.write_text(content, encoding="utf-8")
    result = ReadTool(project_root=tmp_path).execute(
        {"path": "last_full_line.txt"}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]

    assert result.ok is True
    assert returned[-1] in original
    assert "L1" in returned

    last_line_position = len(returned)
    assert f"offset={last_line_position + 1}" in result.output

def test_read_hint_reports_next_offset_and_remaining(tmp_path: Path) -> None:
    file = tmp_path / "hint.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    file.write_text(content, encoding="utf-8")
    result = ReadTool(project_root=tmp_path).execute(
        {"path": "hint.txt", "offset": 51, "limit": 10}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]
    n_returned = len(returned)

    assert result.ok is True
    assert n_returned == 10
    assert "L51" in returned
    assert "L60" in returned
    assert "offset=61" in result.output
    assert "remaining=40" in result.output    

def test_read_no_hint_when_reaching_end(tmp_path: Path) -> None:
    file = tmp_path / "no_hint.txt"
    content = "\n".join(f"L{i}" for i in range(1, 101))
    file.write_text(content, encoding="utf-8")
    result = ReadTool(project_root=tmp_path).execute(
        {"path": "no_hint.txt", "offset": 91, "limit": 10}
    )
    returned = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]
    n_returned = len(returned)

    assert result.ok is True
    assert n_returned == 10
    assert "L91" in returned
    assert "L100" in returned
    assert "offset=" not in result.output
    