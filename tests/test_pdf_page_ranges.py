"""Regression coverage for string page ranges in PDF image actions."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import pdf_read


class _Pixmap:
    width = 100
    height = 200

    def tobytes(self, image_format):
        return f"{image_format}-bytes".encode()


class _Page:
    def get_images(self):
        return []

    def get_pixmap(self, *, matrix):
        return _Pixmap()


class _Document:
    page_count = 6

    def __init__(self):
        self.accessed_pages = []
        self.closed = False

    def __getitem__(self, page_num):
        self.accessed_pages.append(page_num)
        return _Page()

    def close(self):
        self.closed = True


def _action_patches(document):
    stash_file = MagicMock()
    stash_file.save_binary.side_effect = lambda **kwargs: {
        "ref": f"stash://space_test/{kwargs['name']}"
    }
    return (
        patch.object(pdf_read, "resolve_pdf_path", return_value="sample.pdf"),
        patch.object(pdf_read.fitz, "open", return_value=document),
        patch.object(
            pdf_read,
            "open_space",
            return_value=(SimpleNamespace(space_id="space_test"), True),
        ),
        patch.object(pdf_read, "StashFile", return_value=stash_file),
    )


def test_extract_images_honors_string_page_range():
    document = _Document()
    patches = _action_patches(document)

    with patches[0], patches[1], patches[2], patches[3]:
        result = pdf_read.action_extract_images({"pages": "2-4"})

    assert result["ok"] is True
    assert document.accessed_pages == [1, 2, 3]
    assert document.closed is True


def test_to_images_honors_string_page_range():
    document = _Document()
    patches = _action_patches(document)

    with patches[0], patches[1], patches[2], patches[3]:
        result = pdf_read.action_to_images({"pages": "2-4"})

    assert result["ok"] is True
    assert [image["page"] for image in result["data"]["images"]] == [2, 3, 4]
    assert document.accessed_pages == [1, 2, 3]
    assert document.closed is True
