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
