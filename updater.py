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

    def get_preferred_asset(self) -> Optional[ReleaseAsset]:
        """Automatically select the best asset based on current runtime environment."""
        is_frozen = getattr(sys, "frozen", False)
        current_exe = Path(sys.executable).resolve()
        is_installed = is_frozen and (current_exe.parent / "unins000.exe").exists()

        if is_frozen and not is_installed:
            standalone = self.get_asset("standalone")
            if standalone:
                return standalone

        return self.get_asset("installer") or self.get_asset("standalone") or (self.assets[0] if self.assets else None)


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
        progress_cb: Optional[Callable[..., None]] = None,
        asset_name: str = "SmartDownloadManager-Update.exe",
        before_restart_cb: Optional[Callable[[], None]] = None,
    ) -> bool:
        """
        Download the update asset to %TEMP%\\SDM_Update\\ and launch it.

        For *Setup.exe assets: launches silently with /SILENT /CLOSEAPPLICATIONS and restarts the app.
        For standalone .exe:  waits for process exit, overwrites executable, and restarts.
        For *.zip (portable): opens the containing folder so the user can extract manually.

        Returns True on success, False on failure.
        """
        def _report(frac: float, dl: int, tot: int) -> None:
            if not progress_cb:
                return
            try:
                import inspect
                sig = inspect.signature(progress_cb)
                if len(sig.parameters) >= 3:
                    progress_cb(frac, dl, tot)
                else:
                    progress_cb(frac)
            except Exception:
                try:
                    progress_cb(frac)
                except Exception:
                    pass

        try:
            import urllib.request

            tmp_dir = Path(tempfile.gettempdir()) / "SDM_Update"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            dest_path = tmp_dir / asset_name

            log.info(f"Downloading update asset: {download_url} → {dest_path}")

            # Stream download with progress reporting
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": f"SmartDownloadManager/{CURRENT_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
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
                        if total > 0:
                            _report(downloaded / total, downloaded, total)

            _report(1.0, downloaded, total)
            log.info(f"Update asset saved to: {dest_path}")

            # Run graceful shutdown hook (e.g. stop downloads, save queue state, stop tray/bridge)
            if before_restart_cb:
                try:
                    before_restart_cb()
                except Exception as exc:
                    log.warning(f"before_restart_cb error: {exc}")

            is_windows = sys.platform == "win32"
            is_frozen = getattr(sys, "frozen", False)
            current_exe = Path(sys.executable).resolve()
            asset_lower = asset_name.lower()

            if is_windows and asset_lower.endswith(".exe"):
                bat_path = tmp_dir / "apply_update.bat"
                is_setup = "setup" in asset_lower

                if is_setup:
                    # Inno Setup installer:
                    # Run silent setup, then relaunch application
                    bat_content = (
                        "@echo off\r\n"
                        "echo Updating Smart Download Manager...\r\n"
                        f'start /wait "" "{dest_path}" /SILENT /CLOSEAPPLICATIONS\r\n'
                    )
                    if is_frozen:
                        bat_content += f'start "" "{current_exe}"\r\n'
                    bat_content += "exit\r\n"
                else:
                    # Standalone executable:
                    # Wait for process exit to release file lock, overwrite, and relaunch
                    bat_content = (
                        "@echo off\r\n"
                        "echo Updating Smart Download Manager standalone...\r\n"
                        "timeout /t 2 /nobreak > nul\r\n"
                        f'move /y "{dest_path}" "{current_exe}"\r\n'
                    )
                    if is_frozen:
                        bat_content += f'start "" "{current_exe}"\r\n'
                    bat_content += "exit\r\n"

                bat_path.write_text(bat_content, encoding="utf-8")

                # Launch batch script in detached process
                DETACHED_FLAGS = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                subprocess.Popen(
                    ["cmd.exe", "/c", str(bat_path)],
                    creationflags=DETACHED_FLAGS,
                    close_fds=True,
                )
                log.info("Update batch script launched. Terminating current process.")
                time.sleep(0.5)
                os._exit(0)
            elif is_windows and asset_lower.endswith(".zip"):
                # Portable ZIP – open folder for manual extraction
                os.startfile(str(tmp_dir))
            else:
                log.info(f"Update asset ready at: {dest_path}")

            return True

        except Exception as exc:
            log.error(f"Update download/apply failed: {exc}")
            return False
