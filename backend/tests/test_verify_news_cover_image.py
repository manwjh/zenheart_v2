"""Tests for verify_news_cover_image_url (local MEDIA_ROOT + HTTP resolution)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.image_check import (
    absolute_url_for_http_fetch,
    local_media_file_for_url,
    verify_news_cover_image_url,
)


def test_absolute_url_for_http_fetch():
    assert absolute_url_for_http_fetch("/media/x.png", public_site_base_url="https://ex.com") == (
        "https://ex.com/media/x.png"
    )
    assert absolute_url_for_http_fetch("https://cdn/a.jpg", public_site_base_url="") == "https://cdn/a.jpg"
    assert absolute_url_for_http_fetch("/x", public_site_base_url="") is None


def test_local_media_file_for_url_resolves(tmp_path: Path):
    root = tmp_path / "media_root"
    img = root / "images" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")

    got = local_media_file_for_url("/media/images/a.png", media_root=str(root))
    assert got == img.resolve()


def test_local_media_file_for_url_rejects_traversal(tmp_path: Path):
    root = tmp_path / "media_root"
    root.mkdir()
    assert local_media_file_for_url("/media/../secrets", media_root=str(root)) is None


def test_verify_news_cover_missing_file_under_media_root(tmp_path: Path):
    root = tmp_path / "media_root"
    root.mkdir()
    err = asyncio.run(
        verify_news_cover_image_url(
            "/media/images/nope.png",
            public_site_base_url="https://example.com",
            media_root=str(root),
        )
    )
    assert err is not None
    assert "does not exist" in err


def test_verify_news_cover_ok_local(tmp_path: Path):
    root = tmp_path / "media_root"
    img = root / "images" / "b.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"ok")

    err = asyncio.run(
        verify_news_cover_image_url(
            "/media/images/b.png",
            public_site_base_url="",
            media_root=str(root),
        )
    )
    assert err is None
