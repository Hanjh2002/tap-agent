"""Test EditTool."""

from __future__ import annotations

from pathlib import Path

import pytest
from tap.tools.edit import Edit, EditTool, EditArgs, EditError, apply_edits


def test_edit_replaces_unique_text(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("def foo():\n    return 1\n")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "edits": [Edit(old="return 1", new="return 42")],
    })

    assert result.ok is True
    assert file.read_text() == "def foo():\n    return 42\n"


def test_edit_fails_when_text_not_found(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("hello world")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "edits": [Edit(old="not there", new="x")],
    })

    assert result.ok is False
    assert "not found" in result.output.lower()
    assert file.read_text() == "hello world"


def test_edit_fails_when_text_appears_multiple_times(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("x = 1\ny = 1\nz = 1\n")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "edits": [Edit(old="= 1", new="= 2")],
    })

    assert result.ok is False
    assert "3 times" in result.output
    assert file.read_text() == "x = 1\ny = 1\nz = 1\n"


def test_edit_missing_file_fails(tmp_path: Path) -> None:
    result = EditTool(project_root=tmp_path).execute({
        "path": "notfound.txt",
        "edits": [Edit(old="x", new="y")],
    })

    assert result.ok is False
    assert "not found" in result.output.lower()


def test_edit_directory_path_fails(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    result = EditTool(project_root=tmp_path).execute({
        "path": "subdir",
        "edits": [Edit(old="x", new="y")],
    })

    assert result.ok is False
    assert "directory" in result.output.lower()


def test_edit_denies_path_traversal(tmp_path: Path) -> None:
    result = EditTool(project_root=tmp_path).execute({
        "path": "../../etc/hosts",
        "edits": [Edit(old="x", new="y")],
    })

    assert result.ok is False
    assert "outside" in result.output.lower()


def test_edit_preserves_unique_context(tmp_path: Path) -> None:
    file = tmp_path / "test.py"
    file.write_text("x = 1\ny = 1\n")

    result = EditTool(project_root=tmp_path).execute({
        "path": "test.py",
        "edits": [Edit(old="x = 1", new="x = 999")],
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
    assert "edits" in schema["properties"]
    assert set(schema["required"]) == {"path", "edits"}


def test_edit_preserves_crlf(tmp_path: Path) -> None:
    file = tmp_path / "crlf.py"
    file.write_bytes(b"def foo():\r\n    return 1\r\n")

    result = EditTool(project_root=tmp_path).execute({
        "path": "crlf.py",
        "edits": [Edit(old="return 1", new="return 2")],
    })

    assert result.ok is True
    assert file.read_bytes() == b"def foo():\r\n    return 2\r\n"


def test_edit_preserves_bom(tmp_path: Path) -> None:
    file = tmp_path / "bom.txt"
    file.write_bytes(b"\xef\xbb\xbfhello world")

    result = EditTool(project_root=tmp_path).execute({
        "path": "bom.txt",
        "edits": [Edit(old="world", new="there")],
    })

    assert result.ok is True
    assert file.read_bytes() == b"\xef\xbb\xbfhello there"


def write_file(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.write_text(content, encoding="utf-8")
    return path


def test_single_edit_replaces_once() -> None:
    assert apply_edits(
        "hello world",
        [Edit(old="world", new="there")],
    ) == "hello there"

def test_old_matching_twice_raises_ambiguous():
    with pytest.raises(EditError) as exc:
        apply_edits("a a a", 
                    [Edit(old="a", new="b")])
    assert exc.value.reason == "ambiguous"
    assert exc.value.index == 1

def test_old_absent_raises_not_found():
    with pytest.raises(EditError) as exc:
        apply_edits("hello",
                    [Edit(old="xyz", new="q")])
    assert exc.value.reason == "not_found"
    assert exc.value.index == 1

def test_empty_old_raises_empty():
    with pytest.raises(EditError) as exc:
        apply_edits("hello",
                    [Edit(old="", new="q")])
    assert exc.value.reason == "empty_old"
    assert exc.value.index == 1

def test_old_equal_new_raises_no_operation():
    with pytest.raises(EditError) as exc:
        apply_edits("hello",
                    [Edit(old="hi", new="hi")]
                    )

    assert exc.value.reason == "no_operation" 
    assert exc.value.index == 1

def test_overlapping_edits_raise_with_both_indices():
    with pytest.raises(EditError) as exc:
        apply_edits("abcdef",
                    [Edit(old="abc", new="X"), Edit(old="cde", new="Y")]
                )
    assert exc.value.reason == "overlap"
    assert {exc.value.index, exc.value.other_index} == {1, 2}

def test_adjacent_is_not_overlap():
    assert apply_edits(
        "abcdef",
        [Edit(old="abc", new="X"), Edit(old="def", new="Y")]
        ) == "XY"

    assert apply_edits(
        "abcdef", 
        [Edit(old="def", new="Y"), Edit(old="abc", new="X")]
        ) == "XY"

def test_output_independent_of_edit_order():
    assert apply_edits(
        "abcdef",
        [Edit(old="abc", new="X"), Edit(old="def", new="Y")]
        ) == "XY"

    assert apply_edits(
        "abcdef",
        [Edit(old="def", new="Y"), Edit(old="abc", new="X")]
        ) == "XY"

def test_edits_resolved_against_original_not_intermediate():
    assert apply_edits("a b",
                       [Edit(old="a", new="b"),
                            Edit(old="b", new="c")]
                       ) == "b c"

def test_atomic_third_edit_fails_leaves_file_untouched(tmp_path):
    path = write_file(tmp_path, 
                      "f.txt",
                      "abcdefghi")   
    before = path.read_bytes()

    tool = EditTool(project_root=tmp_path)
    result = tool.execute({
        "path": "f.txt",
        "edits": [Edit(old="abc", new="X"),
                  Edit(old="def", new="Y"),
                  Edit(old="mno", new="Z")]
    })

    after = path.read_bytes()
    assert after == before
    assert result.ok is False
    assert "not found" in result.output.lower()
    assert "3" in result.output

def test_multiple_valid_edits_all_applied(tmp_path: Path) -> None:
    path = write_file(tmp_path, "f.txt", "abcdefghi")

    result = EditTool(project_root=tmp_path).execute({
        "path": "f.txt",
        "edits": [Edit(old="abc", new="X"), Edit(old="def", new="Y")],
    })

    assert result.ok is True
    assert path.read_text() == "XYghi"

def test_apply_edits_prints_nothing_to_stdout(capsys) -> None:
    """apply_edits should not print anything to stdout (to avoid debug logs)."""
    out = apply_edits(
        "alpha\nbeta\n", 
        [Edit(old="alpha", new="A"), Edit(old="beta", new="B")])
    
    assert out == "A\nB\n"
    captured = capsys.readouterr()
    assert captured.out == "", f"apply_edits should not print to stdout: {captured.out!r}"
