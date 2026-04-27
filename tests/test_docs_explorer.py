from pathlib import Path

import importlib.util
import pytest


PROJECT_ROOT = Path(__file__).parent.parent
MODULE_PATH = PROJECT_ROOT / 'jarvis-docs' / 'server' / 'services' / 'docs_explorer.py'
SPEC = importlib.util.spec_from_file_location('jarvis_docs_explorer', MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

DocsExplorerError = MODULE.DocsExplorerError
DocsExplorerService = MODULE.DocsExplorerService


@pytest.fixture()
def docs_root(tmp_path: Path) -> Path:
    root = tmp_path / 'docs'
    (root / 'guides').mkdir(parents=True)
    (root / 'images').mkdir(parents=True)
    (root / 'README.md').write_text('# Home\n\nWelcome to Jarvis docs.\n', encoding='utf-8')
    (root / 'guides' / 'alpha.md').write_text(
        '# Alpha Guide\n\nSearchable paragraph about auth middleware reuse.\n',
        encoding='utf-8',
    )
    (root / 'images' / 'diagram.png').write_bytes(b'png')
    return root


def test_lists_root_and_subfolders(docs_root: Path) -> None:
    service = DocsExplorerService(docs_root=docs_root)

    folders = service.list_folders()

    assert folders[0]['label'] == 'All Docs'
    assert any(folder['path'] == 'guides' for folder in folders)


def test_search_matches_content_and_returns_preview(docs_root: Path) -> None:
    service = DocsExplorerService(docs_root=docs_root)

    result = service.list_documents(search='middleware')

    assert result['total'] == 1
    assert result['documents'][0]['path'] == 'guides/alpha.md'
    assert 'middleware' in result['documents'][0]['preview'].lower()


def test_read_document_extracts_outline(docs_root: Path) -> None:
    service = DocsExplorerService(docs_root=docs_root)

    payload = service.read_document('README.md')

    assert payload['title'] == 'Home'
    assert payload['outline'][0]['title'] == 'Home'


def test_edit_disabled_blocks_save(docs_root: Path) -> None:
    service = DocsExplorerService(docs_root=docs_root, edit_enabled=False)

    with pytest.raises(DocsExplorerError):
        service.save_document('README.md', '# Updated\n')


def test_edit_enabled_updates_markdown_only(docs_root: Path) -> None:
    service = DocsExplorerService(docs_root=docs_root, edit_enabled=True)

    updated = service.save_document('README.md', '# Updated\n\nFresh content.\n')

    assert updated['title'] == 'Updated'
    assert service.read_document('README.md')['content'].startswith('# Updated')


def test_asset_resolution_stays_inside_docs_root(docs_root: Path) -> None:
    service = DocsExplorerService(docs_root=docs_root)

    assert service.resolve_asset('images/diagram.png').name == 'diagram.png'

    with pytest.raises(DocsExplorerError):
        service.resolve_asset('../config/cloud.env')
