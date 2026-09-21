"""Read tool — read an UTF-8 text file.

v1: adds path safety via resolve_within_project.
v2:  also takes extra_read_roots (the skills directories). read may read within
    project_root OR these directories. write/edit/bash are NOT widened —
    least privilege: the model can read skills but can't write/run outside the project.
v5: adds offset and limit for reading selected line ranges.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from typing import Literal
from pydantic import BaseModel, Field

from tap.tools._paths import PathOutsideProject, resolve_within_roots
from tap.tools.base import BaseTool, ToolResult


# These five states are the possible outcomes of selecting lines; they form an
# enum in disguise, and _render maps each one to a different output format.
# File contains no lines to read.
EMPTY = "empty"

# Requested offset is beyond the end of the file.
PAST_END = "past_end"

# A single line exceeds the maximum character limit.
OVERSIZE = "oversize"

# More content remains after reaching the maximum character.
MORE = "more"

# Selected lines reach the end of the file.
COMPLETE = "complete"

# Not every field is meaningful in every state. For example, next_offset and
# remaining are meaningless for EMPTY/PAST_END; _render only reads fields that
# are valid for the selected state.
class Selection(BaseModel):
    """A selection of content from a file."""
    body: list[str]
    state: Literal["empty", "past_end", "oversize", "more", "complete"]
    next_offset: int
    remaining: int
    requested_offset: int
    file_len: int
    shown_chars: int

def _select_lines(all_lines, offset, limit, max_chars) -> Selection:
    """Select lines from all_lines, with offset and limit."""
    total = len(all_lines)
    # An empty file produces [''] from ''.split('\n'), not []. Therefore the
    # content check is required; len(all_lines) == 0 is never true here.
    if all_lines == [""]:
        return Selection(
            body=[],
            state=EMPTY,
            next_offset=0,
            remaining=0,
            requested_offset=offset,
            file_len=0,
            shown_chars = 0,
        )

    start = offset - 1
    if start >= total:
        return Selection(
            body=[],
            state=PAST_END,
            next_offset=0,
            remaining=0,
            requested_offset=offset,
            file_len=total,
            shown_chars = 0,
        )

    end = min(start + limit, total)
    candidate = all_lines[start:end]
    n_taken = 0   # number of lines taken 
    running = 0   # total number of chars taken

    # If the first line exceeds the cap by itself, taking zero lines would
    # leave next_offset == offset and make the model read the same line forever.
    # Force one sliced line so the invariant "never return zero lines when
    # start < total" always holds.
    # +1 proxies the newline character; it is slightly conservative but keeps
    # the cap as a safety boundary.
    if len(candidate[0]) + 1 > max_chars:
        n_taken += 1
        next_offset = offset + n_taken
        return Selection(
            body=[candidate[0][:max_chars]],
            state=OVERSIZE,
            next_offset=next_offset,
            remaining=total - next_offset + 1,
            requested_offset=offset,
            file_len=total,
            shown_chars = max_chars,
        )

    # This loop only counts n_taken. It does not return or build Selection;
    # next_offset, remaining, and state are all derived after the loop.
    for line in candidate:
        new_running = running + len(line) + 1
        
        if new_running > max_chars:
            break

        running = new_running
        n_taken += 1

    next_offset = offset + n_taken
    remaining = total - next_offset + 1
        
    # Stopping for the line limit, character cap, or end of file is unified
    # here: one comparison distinguishes remaining lines from a complete read.
    return Selection(
        body=candidate[:n_taken],
        state=MORE if next_offset<= total else COMPLETE,
        next_offset=next_offset,
        remaining=remaining,
        requested_offset=offset,
        file_len=total,
        shown_chars = max_chars,
        )

def _render(selection: Selection, path) -> str:
    body_text = "\n".join(selection.body)
    # Metadata must start on its own line with "\n\n[". Tests filter content
    # lines using not startswith("["); appending metadata to a content line
    # would break that hidden coupling.
    if selection.state == EMPTY:
        return "[File is empty!]"
    
    elif selection.state == PAST_END:
        return (
            body_text + 
            f"\n\n[offset={selection.requested_offset}, file_len={selection.file_len} — {path}]"
        )

    elif selection.state == MORE:
        return (
            body_text +
            f"\n\n[offset={selection.next_offset}, remaining={selection.remaining} — {path}]"
        )

    elif selection.state == COMPLETE:
        return body_text
    
    elif selection.state == OVERSIZE:
        return (
            body_text +
            f"\n\n[truncated — {path} has {selection.file_len} chars, showing first {selection.shown_chars} ]"
        )

    else:
        raise ValueError(f"unknown state {selection.state}")
        
class ReadArgs(BaseModel):
    path: str = Field(..., 
                      description="Path to file to read (relative to project root)")
    offset: int = Field(1, 
                        ge=1, 
                        description="1-indexed line number to start reading from")
    limit: int = Field(2000, 
                       ge=1, 
                       description="Maximum number of lines to return")

class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read a UTF-8 text file inside the project directory and return its content. "
        "Use this to examine source code, config files, or documentation. "
        "Fails if file doesn't exist, is a directory, is not UTF-8 text, "
        "or resolves outside the project root."
    )
    args_model = ReadArgs

    MAX_CHARS = 50_000

    def __init__(self, project_root: Path, extra_read_roots: Sequence[Path] = ()):
        self._project_root = project_root
        self._extra_read_roots = tuple(extra_read_roots)  # skills directories

    def _run(self, args: ReadArgs) -> ToolResult:
        roots = [self._project_root, *self._extra_read_roots]  # project come first
        try:
            path = resolve_within_roots(args.path, roots)
        except PathOutsideProject as e:
            return ToolResult(output=str(e), ok=False)

        if not path.exists():
            return ToolResult(output=f"File not found: {args.path}", ok=False)
        if path.is_dir():
            return ToolResult(output=f"Path is a directory, not a file: {args.path}", ok=False)

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(
                output=f"File is not valid UTF-8 text: {args.path}",
                ok=False,
            )
        except PermissionError:
            return ToolResult(output=f"Permission denied: {args.path}", ok=False)

        sel = _select_lines(text.split("\n"), 
                            args.offset, 
                            args.limit, 
                            self.MAX_CHARS)

        return ToolResult(output=_render(sel, args.path), ok=True)
    