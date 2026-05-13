from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path


def _resolve_skills_dir() -> Path:
    """
    OpenClaw skill bundles (<slug>/SKILL.md).

    Prefer ZENHEART_SKILLS_DIR when set (absolute path).
    Else `zenheart-agent/skills/` next to `v2/` given this file lives under `v2/backend/app/`.
    """
    override = os.environ.get("ZENHEART_SKILLS_DIR")
    if override is None:
        raw = ""
    else:
        raw = override.strip()
    if raw != "":
        return Path(raw).resolve()
    v2_app_root = Path(__file__).resolve().parent.parent.parent.parent
    return (v2_app_root.parent / "zenheart-agent" / "skills").resolve()


# Both the REST router (faq_public) and the WS handlers import this constant.
SKILLS_DIR: Path = _resolve_skills_dir()

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


def skill_zip_bytes(slug: str) -> bytes | None:
    """
    Return a deflated zip of the published skill: OpenClaw bundle (whole directory)
    or a single root-level <slug>.md. Returns None if the slug is invalid or missing.
    """
    if not is_valid_slug(slug):
        return None
    bundle = SKILLS_DIR / slug
    if (bundle / "SKILL.md").is_file():
        root = bundle.resolve()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(bundle.rglob("*")):
                if not path.is_file():
                    continue
                if any(part.startswith(".") for part in path.parts):
                    continue
                try:
                    resolved = path.resolve()
                    resolved.relative_to(root)
                except ValueError:
                    continue
                rel = path.relative_to(bundle)
                zf.write(path, f"{slug}/{rel.as_posix()}")
        return buf.getvalue()
    flat = skill_markdown_path(slug)
    if flat is None or not flat.is_file() or flat.parent != SKILLS_DIR:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(flat, f"{slug}.md")
    return buf.getvalue()
