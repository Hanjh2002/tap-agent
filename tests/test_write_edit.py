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


# ---------- EditTool ----------

def test_edit_replaces_unique_text(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("def foo():\n    return 1\n")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "old_text": "return 1",
        "new_text": "return 42",
    })

    assert result.ok is True
    assert file.read_text() == "def foo():\n    return 42\n"


def test_edit_fails_when_text_not_found(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("hello world")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "old_text": "not there",
        "new_text": "x",
    })

    assert result.ok is False
    assert "not found" in result.output.lower()
    assert file.read_text() == "hello world"


def test_edit_fails_when_text_appears_multiple_times(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("x = 1\ny = 1\nz = 1\n")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "old_text": "= 1",
        "new_text": "= 2",
    })

    assert result.ok is False
    assert "3 times" in result.output
    assert file.read_text() == "x = 1\ny = 1\nz = 1\n"


def test_edit_missing_file_fails(tmp_path: Path) -> None:
    result = EditTool(project_root=tmp_path).execute({
        "path": "notfound.txt",
        "old_text": "x",
        "new_text": "y",
    })

    assert result.ok is False
    assert "not found" in result.output.lower()


def test_edit_directory_path_fails(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    result = EditTool(project_root=tmp_path).execute({
        "path": "subdir",
        "old_text": "x",
        "new_text": "y",
    })

    assert result.ok is False
    assert "directory" in result.output.lower()


def test_edit_denies_path_traversal(tmp_path: Path) -> None:
    result = EditTool(project_root=tmp_path).execute({
        "path": "../../etc/hosts",
        "old_text": "x",
        "new_text": "y",
    })

    assert result.ok is False
    assert "outside" in result.output.lower()


def test_edit_preserves_unique_context(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("x = 1\ny = 1\n")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "old_text": "x = 1",
        "new_text": "x = 999",
    })

    assert result.ok is True
    assert file.read_text() == "x = 999\ny = 1\n"


def test_edit_missing_args_fails(tmp_path: Path) -> None:
    result = EditTool(project_root=tmp_path).execute({"path": "foo"})

    assert result.ok is False
    assert "invalid arguments" in result.output.lower()


def test_edit_input_schema(tmp_path: Path) -> None:
    schema = EditTool(project_root=tmp_path).input_schema

    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "old_text" in schema["properties"]
    assert "new_text" in schema["properties"]
    assert set(schema["required"]) == {"path", "old_text", "new_text"}

def test_edit_preserves_crlf(tmp_path):
    f = tmp_path / "crlf.py"
    f.write_bytes(b"def foo():\r\n    return 1\r\n")

    tool = EditTool(project_root=tmp_path)
    result = tool.execute({
        "path": "crlf.py",
        "old_text": "return 1",
        "new_text": "return 2",
    })

    assert result.ok
    assert f.read_bytes() == b"def foo():\r\n    return 2\r\n"


def test_edit_preserves_bom(tmp_path):
    f = tmp_path / "bom.txt"
    f.write_bytes(b"\xef\xbb\xbfhello world")

    tool = EditTool(project_root=tmp_path)
    result = tool.execute({
        "path": "bom.txt",
        "old_text": "world",
        "new_text": "there",
    })

    assert result.ok
    assert f.read_bytes() == b"\xef\xbb\xbfhello there"