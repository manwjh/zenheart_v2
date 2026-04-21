from pathlib import Path


def resolve_markdown_path(markdown_path: str, news_markdown_root: str) -> Path:
    """Resolve a stored markdown_path to an absolute Path.

    New WS-published articles store a relative path (e.g. news_ws/<hex>.md).
    Legacy admin-created articles store an absolute path.

    When the path is relative, NEWS_MARKDOWN_ROOT must be set; the resolved
    path is validated to stay within the root (path traversal guard).
    """
    p = Path(markdown_path)
    if p.is_absolute():
        return p

    root_raw = news_markdown_root.strip()
    if not root_raw:
        raise ValueError(
            "markdown_path is relative but NEWS_MARKDOWN_ROOT is not configured."
        )

    root = Path(root_raw).resolve()
    resolved = (root / p).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Resolved markdown path escaped root: {resolved}") from exc

    return resolved
