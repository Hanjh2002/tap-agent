"""Test WriteTool và EditTool.

v4: tools nhận project_root, chặn path traversal.
"""

from __future__ import annotations

from pathlib import Path

from tap.tools.edit import EditTool
from tap.tools.write import WriteTool


# ---------- WriteTool ----------

def test_write_creates_new_file(tmp_path: Path) -> None:
    result = WriteTool(project_root=tmp_path).execute({
        "path": "new.txt",
        "content": "hello",
    })

    assert result.ok is True
    assert (tmp_path / "new.txt").read_text() == "hello"


def test_write_overwrites_existing_file(tmp_path: Path) -> None:
    file = tmp_path / "existing.txt"
    file.write_text("old content")

    result = WriteTool(project_root=tmp_path).execute({
        "path": "existing.txt",
        "content": "new content",
    })

    assert result.ok is True
    assert file.read_text() == "new content"


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    result = WriteTool(project_root=tmp_path).execute({
        "path": "deep/nested/file.txt",
        "content": "hi",
    })

    assert result.ok is True
    assert (tmp_path / "deep" / "nested" / "file.txt").read_text() == "hi"


def test_write_directory_path_fails(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    result = WriteTool(project_root=tmp_path).execute({
        "path": "subdir",
        "content": "x",
    })

    assert result.ok is False
    assert "directory" in result.output.lower()


def test_write_denies_path_traversal(tmp_path: Path) -> None:
    result = WriteTool(project_root=tmp_path).execute({
        "path": "../../evil.txt",
        "content": "x",
    })

    assert result.ok is False
    assert "outside" in result.output.lower()


def test_write_reports_size(tmp_path: Path) -> None:
    result = WriteTool(project_root=tmp_path).execute({
        "path": "multi.txt",
        "content": "line1\nline2\nline3",
    })

    assert result.ok is True
    assert "17 chars" in result.output
    assert "3 lines" in result.output


def test_write_missing_args_fails(tmp_path: Path) -> None:
    result = WriteTool(project_root=tmp_path).execute({})

    assert result.ok is False
    assert "invalid arguments" in result.output.lower()


def test_write_input_schema(tmp_path: Path) -> None:
    schema = WriteTool(project_root=tmp_path).input_schema

    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "content" in schema["properties"]
    assert set(schema["required"]) == {"path", "content"}

