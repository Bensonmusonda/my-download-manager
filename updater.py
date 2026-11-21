"""
updater.py — In-App GitHub Releases Self-Updater for Smart Download Manager.

Flow:
  1. Query https://api.github.com/repos/Bensonmusonda/my-download-manager/releases/latest
  2. Compare remote tag_name vs current version (semver).
  3. Return UpdateInfo (release notes, assets) if newer version found.
  4. download_and_apply_update() downloads the asset to %TEMP%\\SDM_Update\\ and
     launches the installer with /SILENT, then exits the current process.

GitHub unauthenticated rate limit: 60 req/hr.
A last-checked timestamp is cached in settings so startup checks are throttled
to at most once every 60 minutes.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

CURRENT_VERSION = "1.3.1"
REPO = "Bensonmusonda/my-download-manager"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

# Minimum seconds between automatic startup checks (1 hour)
AUTO_CHECK_INTERVAL = 3600


# ---------------------------------------------------------------------------
# Data Types
# ---------------------------------------------------------------------------

@dataclass
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    content_type: str


@dataclass
class UpdateInfo:
    remote_version: str          # e.g. "1.3.0"
    tag_name: str                # e.g. "v1.3.0"
    release_notes: str           # Markdown body from GitHub
    html_url: str                # GitHub release page URL
    published_at: str            # ISO 8601
    assets: list[ReleaseAsset] = field(default_factory=list)

    def get_asset(self, kind: str = "installer") -> Optional[ReleaseAsset]:
        """
        Return the best matching asset for the requested kind.

        kind values:
          "installer"  → *Setup.exe
          "standalone" → *.exe (non-Setup)
          "portable"   → *Portable.zip
        """
        for asset in self.assets:
            name = asset.name.lower()
            if kind == "installer" and "setup" in name and name.endswith(".exe"):
                return asset
            if kind == "portable" and "portable" in name and name.endswith(".zip"):
                return asset
        # Standalone: any .exe that isn't the Setup
        if kind == "standalone":
            for asset in self.assets:
                name = asset.name.lower()
                if name.endswith(".exe") and "setup" not in name:
                    return asset
        return None


# ---------------------------------------------------------------------------
# Version Comparison
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '1.2.0' or 'v1.3.0' into a tuple of ints."""
    v = v.lstrip("v").strip()
    parts = re.split(r"[.\-]", v)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            break
    return tuple(result) if result else (0,)


def is_newer(remote: str, current: str) -> bool:
    """Return True if remote version is strictly newer than current."""
    return _parse_version(remote) > _parse_version(current)


# ---------------------------------------------------------------------------
# UpdateChecker
# ---------------------------------------------------------------------------

class UpdateChecker:
    """Lightweight GitHub Releases update checker."""

    REPO = REPO
    API_URL = API_URL

    @classmethod
    def check_for_updates(
        cls,
        current_version: str = CURRENT_VERSION,
        include_prereleases: bool = False,
    ) -> Optional[UpdateInfo]:
        """
        Fetch the latest GitHub release and compare against current_version.

        Returns UpdateInfo if a newer version is available, else None.
        Raises RuntimeError on network failure (caller should catch and display).
        """
        try:
            import urllib.request
            import json as _json

            req = urllib.request.Request(
                cls.API_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"SmartDownloadManager/{current_version}",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode())
        except Exception as exc:
            raise RuntimeError(f"Failed to reach GitHub API: {exc}") from exc

        tag = data.get("tag_name", "")
        remote_ver = tag.lstrip("v")
        is_prerelease = data.get("prerelease", False)

        if is_prerelease and not include_prereleases:
            log.info("Latest GitHub release is a pre-release; skipping (pre-releases disabled).")
            return None

        if not is_newer(remote_ver, current_version):
            log.info(f"Already up to date: local={current_version}, remote={remote_ver}")
            return None

        assets = [
            ReleaseAsset(
                name=a["name"],
                download_url=a["browser_download_url"],
                size=a.get("size", 0),
                content_type=a.get("content_type", ""),
            )
            for a in data.get("assets", [])
        ]

        return UpdateInfo(
            remote_version=remote_ver,
            tag_name=tag,
            release_notes=data.get("body", ""),
            html_url=data.get("html_url", ""),
            published_at=data.get("published_at", ""),
            assets=assets,
        )

    @classmethod
    def should_auto_check(cls, last_checked_ts: float) -> bool:
        """
        Return True if enough time has elapsed since the last check
        (respects the AUTO_CHECK_INTERVAL throttle).
        """
        return (time.time() - last_checked_ts) >= AUTO_CHECK_INTERVAL

    @classmethod
    def download_and_apply_update(
        cls,
        download_url: str,
        progress_cb: Optional[Callable[[float], None]] = None,
        asset_name: str = "SmartDownloadManager-Update.exe",
    ) -> bool:
        """
        Download the update asset to %TEMP%\\SDM_Update\\ and launch it.

        For *Setup.exe assets: launches with /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS
        For *.zip (portable):  opens the containing folder so the user can extract manually.

        Returns True on success, False on failure.
        """
        try:
            import urllib.request

            tmp_dir = Path(tempfile.gettempdir()) / "SDM_Update"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            dest_path = tmp_dir / asset_name

            log.info(f"Downloading update asset: {download_url} → {dest_path}")

            # Stream download with progress
            with urllib.request.urlopen(download_url, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 65536
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total:
                            progress_cb(downloaded / total)

            if progress_cb:
                progress_cb(1.0)

            log.info(f"Update asset saved to: {dest_path}")

            if asset_name.lower().endswith(".exe"):
                # Inno Setup installer – silent install, restart app
                args = [str(dest_path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
                subprocess.Popen(args, shell=False)
                log.info("Installer launched. Exiting current process.")
                # Give the installer a moment to start, then quit
                time.sleep(1.5)
                sys.exit(0)
            else:
                # Portable ZIP – open folder for manual extraction
                if sys.platform == "win32":
                    os.startfile(str(tmp_dir))

            return True

        except Exception as exc:
            log.error(f"Update download/apply failed: {exc}")
            return False
