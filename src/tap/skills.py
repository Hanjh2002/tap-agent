"""Skills loader — discovers and loads skills from registered directories.

Skill is packaged know-how for a KIND of task (unlike AGENTS.md, which is tied
to a specific repo). Each skill is a directory containing a SKILL.md file:

    <root>/<skill-name>/SKILL.md

Loader reads only LIGHT metadata (name + description) to build an "index" to
inject into the system prompt. The BODY of SKILL.md is NOT loaded here — the model
calls the `read` tool on the path itself when a task matches the description (progressive disclosure).

Design decisions:
- name = the DIRECTORY NAME, not the `name` field in frontmatter. The directory name
  is the unique identity, used for de-duplication + handling precedence.
- description = the `description` field in frontmatter; if missing, derived from
  the first content line, so a skill isn't silently dropped.
- precedence: roots are passed in ASCENDING priority order; on a name clash,
  a later root overrides an earlier one (e.g. a project skill overrides a user skill of the same name).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

SKILL_FILENAME = "SKILL.md"


class Skill(BaseModel):
    """Metadata for one skill — enough to build the index, WITHOUT the body.

    `path` is the absolute path to SKILL.md; it's exactly the argument the model will
    pass to the `read` tool when it decides to load the skill's full content.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    path: Path


def load_skills(roots: Sequence[Path]) -> list[Skill]:
    """Scan the roots and return a list of skills de-duplicated by precedence.

    Args:
        roots: Skill directories, in ASCENDING priority order. On a name clash,
            a later entry overrides an earlier one. Non-existent roots are skipped.

    Returns:
        A list of Skills sorted by name — a stable order so the index in the prompt
        doesn't shuffle between runs.
    """
    by_name: dict[str, Skill] = {}
    for root in roots:
        for skill in _scan_root(root):
            by_name[skill.name] = skill  # root sau đè root trước
    return sorted(by_name.values(), key=lambda s: s.name)


def _scan_root(root: Path) -> list[Skill]:
    # Read every valid <root>/<name>/SKILL.md within ONE root.
    if not root.is_dir():
        return []

    skills: list[Skill] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue  # bare .md at root -> not a skill
        skill_file = entry / SKILL_FILENAME
        if not skill_file.is_file():
            continue  # directory without a SKILL.md -> skip
        description = _read_description(skill_file)
        if description is None:
            continue  # empty file, nothing to use as a description -> skip
        skills.append(
            Skill(
                name=entry.name,
                description=description,
                path=skill_file.resolve(),
            )
        )
    return skills


def _read_description(skill_file: Path) -> str | None:
    """Get the description: prefer frontmatter, fall back to the first content line.

     Returns None if the file is completely empty / nothing can be extracted as a description.
    """
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    frontmatter, body = _split_frontmatter(text)
    desc = frontmatter.get("description")
    if desc:
        return desc

    # Fallback: the first non-empty line of the body, stripping leading '#' heading chars.
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return None


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """"Split the YAML frontmatter (the block between two '---') from the body.

    PA MINIMAL parser — deliberately avoids pulling in a YAML dependency. It only
    understands single-line `key: value`, stripping quotes around the value. Enough for
    name + description. If you need full YAML (lists, multiline...), swap in pyyaml.

    Returns (frontmatter dict, remaining body). With no frontmatter, an empty dict
    and body = the original text.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    closing = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closing = i
            break
    if closing is None:
        return {}, text  # frontmatter opened but never closed -> treat as none

    meta: dict[str, str] = {}
    for line in lines[1:closing]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")

    body = "\n".join(lines[closing + 1 :])
    return meta, body


def skill_roots(project_root: Path, home: Path | None = None) -> list[Path]:
    """Skill directories, in ASCENDING priority order (later overrides earlier).

    Precedence (low → high):
        ~/.agents/skills          user, shared standard (lowest)
        ~/.tap/skills             user, tap specific
        <project>/.agents/skills  project, shared standard
        <project>/.tap/skills     project, tap specific (highest)

    Rule: project overrides user; at the same level, tap-specific overrides generic.

    Args:
        project_root:the project root (usually Path.cwd()).
        home: the home directory; None → Path.home(). Kept separate so tests can inject a fake home.
    """
    home = home or Path.home()
    return [
        home / ".agents" / "skills",
        home / ".tap" / "skills",
        project_root / ".agents" / "skills",
        project_root / ".tap" / "skills",
    ]
