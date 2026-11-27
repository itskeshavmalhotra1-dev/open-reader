"""Unit tests for the GitHub Releases updater."""

from book_reader.backend.updater import (
    is_newer_version,
    parse_version,
    select_release_asset,
)


def test_parse_and_compare_versions() -> None:
    assert parse_version("v26.0.0") == (26, 0, 0)
    assert parse_version("26.1") == (26, 1, 0)
    assert is_newer_version("v26.0.1", "26.0.0") is True
    assert is_newer_version("26.1.0", "26.0.0") is True
    assert is_newer_version("v26.0.0", "26.0.0") is False
    assert is_newer_version("25.9.9", "26.0.0") is False


def test_select_release_asset_prefers_setup_exe() -> None:
    assets = [
        {"name": "open-reader-win64.zip", "browser_download_url": "https://example.com/a.zip", "size": 100},
        {"name": "Open-Reader-26.0.0-Setup.exe", "browser_download_url": "https://example.com/setup.exe", "size": 200},
    ]
    chosen = select_release_asset(assets)
    assert chosen is not None
    assert chosen["name"] == "Open-Reader-26.0.0-Setup.exe"


def test_select_release_asset_ignores_non_https() -> None:
    assets = [
        {"name": "Open-Reader-Setup.exe", "browser_download_url": "http://example.com/setup.exe", "size": 200},
    ]
    assert select_release_asset(assets) is None
