"""GitHub Releases updater for Open Reader."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GITHUB_OWNER = "itskeshavmalhotra1-dev"
GITHUB_REPO = "open-reader"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


class UpdateError(RuntimeError):
    """Raised when checking or downloading an update fails."""


@dataclass(frozen=True)
class UpdateInfo:
    """Result of a GitHub release check."""

    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    release_notes: str
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int | None = None


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version tag like 'v26.0.0' or '26.1' into an integer tuple."""
    cleaned = version_str.strip().lstrip("vV")
    parts = [int(m) for m in re.findall(r"\d+", cleaned)]
    if not parts:
        return (0,)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer_version(remote_version: str, current_version: str) -> bool:
    """Return True if remote_version is strictly newer than current_version."""
    return parse_version(remote_version) > parse_version(current_version)


def select_release_asset(assets: list[dict]) -> dict | None:
    """Pick the best Windows installer/package asset from a GitHub release."""
    exe_assets = [
        a for a in assets
        if isinstance(a, dict)
        and str(a.get("name", "")).lower().endswith(".exe")
        and str(a.get("browser_download_url", "")).startswith("https://")
    ]
    if exe_assets:
        for asset in exe_assets:
            name_lower = str(asset.get("name", "")).lower()
            if "setup" in name_lower or "installer" in name_lower:
                return asset
        return exe_assets[0]

    zip_assets = [
        a for a in assets
        if isinstance(a, dict)
        and str(a.get("name", "")).lower().endswith(".zip")
        and str(a.get("browser_download_url", "")).startswith("https://")
    ]
    return zip_assets[0] if zip_assets else None


def check_for_update(current_version: str, timeout: float = 12.0) -> UpdateInfo:
    """Query GitHub Releases for the latest Open Reader version."""
    req = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Open-Reader/{current_version}",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No published releases found on GitHub yet.") from exc
        raise UpdateError(f"GitHub returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise UpdateError(f"Network error while checking for updates: {exc.reason}") from exc
    except Exception as exc:
        raise UpdateError(f"Failed to check for updates: {exc}") from exc

    tag_name = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not tag_name:
        raise UpdateError("Latest GitHub release does not contain a version tag.")

    latest_clean = tag_name.lstrip("vV")
    release_url = str(
        payload.get("html_url")
        or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    )
    release_notes = str(payload.get("body") or "").strip()
    asset = select_release_asset(list(payload.get("assets") or []))

    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_clean,
        update_available=is_newer_version(latest_clean, current_version),
        release_url=release_url,
        release_notes=release_notes,
        asset_name=str(asset["name"]) if asset else None,
        asset_url=str(asset["browser_download_url"]) if asset else None,
        asset_size=int(asset["size"]) if asset and asset.get("size") is not None else None,
    )


def download_update(
    url: str,
    dest_dir: Path,
    filename: str,
    expected_size: int | None = None,
    progress_cb: Callable[[int, int], bool] | None = None,
    timeout: float = 60.0,
) -> Path:
    """Download a release asset over HTTPS into dest_dir and verify its size."""
    if not url.startswith("https://"):
        raise UpdateError("Refusing to download update over a non-HTTPS URL.")

    safe_name = os.path.basename(filename) or "Open-Reader-Setup.exe"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_path = dest_dir / safe_name
    tmp_path = dest_dir / f"{safe_name}.part"

    req = Request(url, headers={"User-Agent": "Open-Reader-Updater"})
    downloaded = 0
    try:
        with urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or expected_size or 0)
            with open(tmp_path, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None and not progress_cb(downloaded, total):
                        raise UpdateError("Update download cancelled.")
    except UpdateError:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise UpdateError(f"Failed to download update: {exc}") from exc

    if downloaded <= 0:
        tmp_path.unlink(missing_ok=True)
        raise UpdateError("Downloaded update file is empty.")
    if expected_size is not None and expected_size > 0 and downloaded != expected_size:
        tmp_path.unlink(missing_ok=True)
        raise UpdateError(
            f"Downloaded size mismatch (expected {expected_size} bytes, got {downloaded})."
        )

    tmp_path.replace(target_path)
    return target_path
