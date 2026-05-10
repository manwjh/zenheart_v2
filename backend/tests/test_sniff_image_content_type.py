"""Tests for sniff_image_content_type (upload must match nginx extension → Content-Type)."""

from app.services.image_check import sniff_image_content_type


def test_sniff_jpeg():
    assert sniff_image_content_type(b"\xff\xd8\xff\xe0\x00\x10JFIF") == "image/jpeg"


def test_sniff_png():
    assert sniff_image_content_type(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") == "image/png"


def test_sniff_gif():
    assert sniff_image_content_type(b"GIF89a\x01\x00\x01\x00") == "image/gif"


def test_sniff_webp():
    assert sniff_image_content_type(b"RIFF\x24\x00\x00\x00WEBP") == "image/webp"


def test_sniff_svg_minimal():
    b = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'
    assert sniff_image_content_type(b) == "image/svg+xml"


def test_sniff_empty_and_garbage():
    assert sniff_image_content_type(b"") is None
    assert sniff_image_content_type(b"not an image") is None
