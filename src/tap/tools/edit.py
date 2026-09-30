"""Edit tool — edits a file by exact string replacement.

v2: adds path safety via resolve_within_project.

Pattern:
- old_text must appear EXACTLY ONCE in the file
- Fails if not found, or if found multiple times
- Forces the LLM to pick an old_text with enough context to be unique
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tap.tools._paths import PathOutsideProject, resolve_within_project
from tap.tools.base import BaseTool, ToolResult


class Edit(BaseModel):
    old: str
    new: str


class EditArgs(BaseModel):
    path: str = Field(..., description="Path to file to edit (relative to project root)")
    edits: list[Edit] = Field(
        ...,
        description=(
            "List of edits; each replaces `old` with `new`. "
            "All validated against the original before any write."
        ),
    )


class EditError(Exception):
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    OVERLAP = "overlap"
    EMPTY_OLD = "empty_old"
    NO_OPERATION = "no_operation"

    def __init__(self, index, reason, message, other_index=None):
        super().__init__(message)
        self.index = index            # 1-indexed
        self.reason = reason
        self.other_index = other_index  # only set for overlap
        self.message = message


UTF8_BOM = "\ufeff"


def _strip_bom(text: str) -> tuple[str, str]:
    return (UTF8_BOM, text[1:]) if text.startswith(UTF8_BOM) else ("", text)


def _detect_line_ending(text: str) -> str:
    crlf = text.find("\r\n")
    lf = text.find("\n")
    if lf == -1 or crlf == -1:
        return "\n"
    return "\r\n" if crlf < lf else "\n"


def _normalize_to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _restore_line_endings(text: str, ending: str) -> str:
    return text.replace("\n", "\r\n") if ending == "\r\n" else text


def apply_edits(original: str, edits: list[Edit]) -> str:
    """Apply a list of exact-text replacements to the original content.

    Each edit must match exactly once in the original string. The function validates
    every replacement first, rejects overlapping replacements, and then applies the
    valid edits in a single pass to produce the updated text.

    Args:
        original: The source text before any edits are applied.
        edits: Ordered replacements to apply. Each item contains the exact text to
            find and the replacement text to insert.

    Returns:
        The updated text with all valid replacements applied.

    Raises:
        EditError: If any replacement is invalid, ambiguous, or overlaps another
            replacement range.
    """
    # Store the character ranges for each replacement in the original text.
    # We use a [start, end) span so we can later reconstruct the output by slicing
    # the original content between edits.
    spans = []

    for i, edit in enumerate(edits):
        # Count how many times the match appears; an exact match must be unique.
        count = original.count(edit.old)
        start = original.find(edit.old)
        end = start + len(edit.old)

        # A no-op edit is rejected because it would otherwise be confusing and
        # could silently produce the same content without any meaningful change.
        if edit.old == edit.new:
            raise EditError(index=i + 1, reason=EditError.NO_OPERATION,
                            message=f"edit #{i + 1}: no operation")

        # Empty old text is not valid for a string-replacement operation.
        if edit.old == "":
            raise EditError(index=i + 1, reason=EditError.EMPTY_OLD,
                            message=f"edit #{i + 1}: empty old text")

        # A replacement is only valid when the target text exists exactly once.
        if count == 0:
            raise EditError(index=i + 1, reason=EditError.NOT_FOUND,
                            message=f"edit #{i + 1}: old text not found")

        if count > 1:
            raise EditError(index=i + 1, reason=EditError.AMBIGUOUS,
                            message=f"edit #{i + 1}: old text found {count} times")

        spans.append((start, end, edit.new))

    # Reject edits that touch the same region of the original string, because the
    # result would be ambiguous and the operations cannot be applied deterministically.
    for a in range(len(spans)):
        for b in range(a + 1, len(spans)):
            if spans[a][0] < spans[b][1] and spans[b][0] < spans[a][1]:
                raise EditError(index=a + 1, other_index=b + 1,
                                reason=EditError.OVERLAP,
                                message=f"edits {a + 1} and {b + 1} overlap")

    # Sort by start position so the output can be rebuilt in a single left-to-right
    # pass over the original string (spans index into the original, not the result).
    spans.sort(key=lambda span: span[0])

    # Rebuild the final text by copying untouched content between replacements and
    # inserting each replacement in place.
    result = ""
    cursor = 0
    for start, end, new in spans:
        result += original[cursor:start] + new
        cursor = end
    result += original[cursor:]
    return result


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file inside the project directory by replacing an exact string with new text. "
        "The old_text must appear EXACTLY ONCE in the file — "
        "if it appears multiple times, include more surrounding context "
        "(such as indentation or adjacent lines) to make it unique. "
        "Use this to modify existing files without rewriting the whole thing. "
        "For creating new files or full rewrites, use 'write' instead. "
        "Fails if path resolves outside the project root."
    )
    args_model = EditArgs

    def __init__(self, project_root: Path):
        self._project_root = project_root

    def _run(self, args: EditArgs) -> ToolResult:
        try:
            path = resolve_within_project(args.path, self._project_root)
        except PathOutsideProject as e:
            return ToolResult(output=str(e), ok=False)

        if not path.exists():
            return ToolResult(output=f"File not found: {args.path}", ok=False)
        if path.is_dir():
            return ToolResult(output=f"Path is a directory: {args.path}", ok=False)

        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                raw = f.read()
        except UnicodeDecodeError:
            return ToolResult(output=f"File is not UTF-8 text: {args.path}", ok=False)
        except PermissionError:
            return ToolResult(output=f"Permission denied reading {args.path}", ok=False)

        bom, content = _strip_bom(raw)
        ending = _detect_line_ending(content)
        normalized = _normalize_to_lf(content)

        norm_edits = [
            Edit(old=_normalize_to_lf(e.old), new=_normalize_to_lf(e.new))
            for e in args.edits
        ]

        try:
            new_content = apply_edits(normalized, norm_edits)
        except EditError as e:
            return ToolResult(output=e.message, ok=False)

        final = bom + _restore_line_endings(new_content, ending)

        try:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(final)
        except PermissionError:
            return ToolResult(output=f"Permission denied writing {args.path}", ok=False)

        n = len(args.edits)
        return ToolResult(output=f"Edited {args.path} ({n} replacement{'s' if n != 1 else ''})")
