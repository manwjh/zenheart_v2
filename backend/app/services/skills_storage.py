from __future__ import annotations

import re
from pathlib import Path

# Absolute path to the v2/skills/ directory on disk.
# Both the REST router (faq_public) and the WS handlers import this constant.
SKILLS_DIR: Path = Path(__file__).parent.parent.parent.parent / "skills"

_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def is_valid_slug(slug: str) -> bool:
    """Return True if slug is safe to use as a filesystem basename."""
    return bool(_SAFE_SLUG.match(slug)) and ".." not in slug


def skill_markdown_path(slug: str) -> Path | None:
    """OpenClaw bundle (`<slug>/SKILL.md`) or legacy flat `<slug>.md` in SKILLS_DIR."""
    if not is_valid_slug(slug):
        return None
    bundle = SKILLS_DIR / slug / "SKILL.md"
    if bundle.is_file():
        return bundle
    flat = SKILLS_DIR / f"{slug}.md"
    if flat.is_file():
        return flat
    return None


def iter_skill_slugs() -> list[str]:
    """
    Slugs for public FAQ listing: bundle dirs with SKILL.md, plus root *.md
    not shadowed by a bundle of the same name.
    """
    if not SKILLS_DIR.is_dir():
        return []
    bundles: set[str] = set()
    for p in SKILLS_DIR.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        if not is_valid_slug(p.name):
            continue
        if (p / "SKILL.md").is_file():
            bundles.add(p.name)
    flats: set[str] = set()
    for p in SKILLS_DIR.glob("*.md"):
        if not is_valid_slug(p.stem):
            continue
        if p.stem in bundles:
            continue
        flats.add(p.stem)
    return sorted(bundles | flats)
