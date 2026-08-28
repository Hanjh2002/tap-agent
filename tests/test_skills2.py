import pytest
from pathlib import Path
from tap.skills import skill_roots, load_skills
from tap.tools.read import ReadTool


def test_skill_roots_precedence_order(tmp_path):
    home = tmp_path / "home"; project = tmp_path / "proj"
    roots = skill_roots(project, home=home)
    # tăng dần ưu tiên: user-generic -> user-tap -> project-generic -> project-tap
    assert roots == [
        home / ".agents" / "skills",
        home / ".tap" / "skills",
        project / ".agents" / "skills",
        project / ".tap" / "skills",
    ]


def test_project_tap_skill_overrides_user(tmp_path):
    home = tmp_path / "home"; project = tmp_path / "proj"
    roots = skill_roots(project, home=home)
    # cùng tên 'x' ở user/.tap và project/.tap
    (home / ".tap" / "skills" / "x").mkdir(parents=True)
    (home / ".tap" / "skills" / "x" / "SKILL.md").write_text(
        "---\ndescription: USER\n---\n", encoding="utf-8")
    (project / ".tap" / "skills" / "x").mkdir(parents=True)
    (project / ".tap" / "skills" / "x" / "SKILL.md").write_text(
        "---\ndescription: PROJECT\n---\n", encoding="utf-8")
    skills = load_skills(roots)
    assert len(skills) == 1
    assert skills[0].description == "PROJECT"   # project thắng


def test_read_CAN_read_skill_outside_project(tmp_path):
    """Trọng tâm hướng 2: read đọc được SKILL.md ở ngoài project."""
    home = tmp_path / "home"; project = tmp_path / "proj"; project.mkdir()
    skdir = home / ".tap" / "skills" / "sec"; skdir.mkdir(parents=True)
    skill_file = skdir / "SKILL.md"
    skill_file.write_text("nội dung skill bí mật", encoding="utf-8")

    roots = skill_roots(project, home=home)
    read = ReadTool(project_root=project, extra_read_roots=roots)

    result = read._run(read.args_model(path=str(skill_file)))
    assert result.ok is True
    assert "nội dung skill" in result.output


def test_read_STILL_blocks_sensitive_files_outside(tmp_path):
    """Nới cho skill KHÔNG mở toang cả máy."""
    home = tmp_path / "home"; project = tmp_path / "proj"; project.mkdir()
    (home / ".tap" / "skills").mkdir(parents=True)
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_rsa").write_text("PRIVATE", encoding="utf-8")

    roots = skill_roots(project, home=home)
    read = ReadTool(project_root=project, extra_read_roots=roots)

    for bad in [str(home / ".ssh" / "id_rsa"), "/etc/passwd", str(home / ".bashrc")]:
        r = read._run(read.args_model(path=bad))
        assert r.ok is False   # chặn


def test_read_default_no_extra_roots_still_locked(tmp_path):
    """Backward-compat: ReadTool(project_root) kiểu cũ vẫn khoá đúng project."""
    project = tmp_path / "proj"; project.mkdir()
    outside = tmp_path / "outside.txt"; outside.write_text("x", encoding="utf-8")
    read = ReadTool(project_root=project)   # không truyền extra_read_roots
    assert read._run(read.args_model(path=str(outside))).ok is False
    