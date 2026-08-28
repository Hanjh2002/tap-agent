import pytest
from pathlib import Path
from tap.skills import load_skills, Skill, _split_frontmatter


def _make_skill(root: Path, name: str, body: str):
    d = root / name; d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return d / "SKILL.md"


def test_loads_skill_with_frontmatter_description(tmp_path):
    _make_skill(tmp_path, "security-review",
                "---\ndescription: Review diff tìm lỗ hổng bảo mật.\n---\n# body\nlàm gì đó")
    skills = load_skills([tmp_path])
    assert len(skills) == 1
    assert skills[0].name == "security-review"
    assert skills[0].description == "Review diff tìm lỗ hổng bảo mật."
    assert skills[0].path.is_absolute()
    assert skills[0].path.name == "SKILL.md"


def test_name_comes_from_dir_not_frontmatter(tmp_path):
    _make_skill(tmp_path, "real-dir-name",
                "---\nname: fake-name\ndescription: x\n---\nbody")
    skills = load_skills([tmp_path])
    assert skills[0].name == "real-dir-name"   # tên thư mục thắng


def test_description_fallback_when_no_frontmatter(tmp_path):
    _make_skill(tmp_path, "no-fm", "# Tiêu đề Skill\nnội dung")
    skills = load_skills([tmp_path])
    assert skills[0].description == "Tiêu đề Skill"   # lấy dòng đầu, bỏ '#'


def test_precedence_later_root_overrides(tmp_path):
    user = tmp_path / "user"; project = tmp_path / "project"
    _make_skill(user, "dup", "---\ndescription: BẢN USER\n---\n")
    _make_skill(project, "dup", "---\ndescription: BẢN PROJECT\n---\n")
    # user trước, project sau (ưu tiên cao hơn)
    skills = load_skills([user, project])
    assert len(skills) == 1
    assert skills[0].description == "BẢN PROJECT"


def test_skips_dir_without_skill_md_and_bare_md(tmp_path):
    (tmp_path / "not-a-skill").mkdir()               # thư mục trống
    (tmp_path / "loose.md").write_text("bare md ở gốc", encoding="utf-8")  # .md trần
    _make_skill(tmp_path, "valid", "---\ndescription: ok\n---\n")
    skills = load_skills([tmp_path])
    assert [s.name for s in skills] == ["valid"]


def test_nonexistent_root_is_ignored(tmp_path):
    assert load_skills([tmp_path / "khong-ton-tai"]) == []


def test_split_frontmatter_unclosed_is_ignored():
    meta, body = _split_frontmatter("---\ndescription: x\nkhông có đóng")
    assert meta == {}   # mở mà không đóng -> coi như không có frontmatter


def test_sorted_by_name(tmp_path):
    for n in ["zebra", "alpha", "mike"]:
        _make_skill(tmp_path, n, f"---\ndescription: {n}\n---\n")
    names = [s.name for s in load_skills([tmp_path])]
    assert names == ["alpha", "mike", "zebra"]
