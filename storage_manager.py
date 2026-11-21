"""
Smart Download Manager — storage_manager.py

Centralized download directory resolution, file-type categorization,
and persistent user application preferences.

Capabilities:
  • Retrieves the native user OS Downloads library folder (cross-platform & Windows registry/KnownFolder).
  • Categorizes downloads by file type into dedicated folders (Images, Videos, Documents, Audio, Archives, Programs, etc.).
  • Resolves download paths either flat in the default folder or organized in a "Smart Downloader" directory structure.
  • Manages atomic loading and saving of user preferences in ~/.smart_download_manager/settings.json.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".smart_download_manager"
CONFIG_FILE = CONFIG_DIR / "settings.json"

SMART_FOLDER_NAME = "Smart Downloader"

# ---------------------------------------------------------------------------
# File Type Category Mappings
# ---------------------------------------------------------------------------

CATEGORY_EXTENSIONS: Dict[str, Set[str]] = {
    "Images": {
        "jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico",
        "tiff", "tif", "avif", "heic", "raw", "psd", "ai", "eps",
    },
    "Videos": {
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v",
        "mpg", "mpeg", "3gp", "ts", "vob", "ogv",
    },
    "Documents": {
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt",
        "rtf", "csv", "epub", "md", "odt", "ods", "odp", "tsv",
        "tex", "log", "pages", "numbers", "key",
    },
    "Audio": {
        "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus",
        "alac", "aiff", "mid", "midi", "mka",
    },
    "Archives": {
        "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "tgz",
        "7-zip", "cab", "lz", "lzma", "z",
    },
    "Programs": {
        "exe", "msi", "apk", "dmg", "pkg", "appimage", "deb", "rpm",
        "bat", "cmd", "ps1", "jar", "bin",
    },
    "Torrents": {
        "torrent",
    },
}

DEFAULT_CATEGORY = "Other"


# ---------------------------------------------------------------------------
# User OS Downloads Library Resolution
# ---------------------------------------------------------------------------

def get_default_download_dir() -> Path:
    """
    Locate the user's default OS Downloads library directory.
    
    On Windows:
      1. Inspects HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders
         for the FOLDERID_Downloads GUID ({374DE290-123F-4565-9164-39C4925E467B}).
      2. If not found or fails, falls back to Path.home() / 'Downloads'.
    
    On macOS / Linux:
      Defaults to Path.home() / 'Downloads'.
    """
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                expanded = os.path.expandvars(val)
                p = Path(expanded).resolve()
                if p.exists() and p.is_dir():
                    return p
        except Exception as exc:
            log.debug(f"Could not read Windows Downloads shell folder from registry: {exc}")

    # Standard fallback
    home_dl = (Path.home() / "Downloads").resolve()
    if home_dl.exists():
        return home_dl

    # Create if missing
    try:
        home_dl.mkdir(parents=True, exist_ok=True)
        return home_dl
    except Exception:
        pass

    return Path.cwd().resolve()


# ---------------------------------------------------------------------------
# File Categorization Helpers
# ---------------------------------------------------------------------------

def extract_file_extension(name_or_url: str) -> str:
    """Extract lowercase file extension without dot from a filename or URL."""
    if not name_or_url:
        return ""

    target = name_or_url.strip()
    if target.startswith("magnet:"):
        return "torrent"

    # Strip query parameters and anchors if present
    parsed = urlparse(target)
    path = parsed.path if parsed.scheme else target
    path = unquote(path)

    # If query had file= parameter, check that too
    if "file=" in parsed.query:
        for part in parsed.query.split("&"):
            if part.startswith("file="):
                val = unquote(part.split("=", 1)[1])
                ext = Path(val).suffix.lstrip(".").lower()
                if ext:
                    return ext

    filename = Path(path).name
    return Path(filename).suffix.lstrip(".").lower()


def get_file_category(
    name_or_url: str,
    custom_categories: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Determine the category folder name ('Images', 'Videos', 'Documents', etc.)
    for a given URL or filename based on its extension.

    If custom_categories is supplied (dict mapping category name → list of
    extensions), those are checked *first* before the built-in defaults,
    giving user-defined categories priority.
    """
    if not name_or_url:
        return DEFAULT_CATEGORY

    target = name_or_url.strip()
    if target.startswith("magnet:") or target.endswith(".torrent"):
        return "Torrents"

    ext = extract_file_extension(target)
    if not ext:
        return DEFAULT_CATEGORY

    # 1. Custom categories take priority
    if custom_categories:
        for category, exts in custom_categories.items():
            if ext in {e.lower().strip() for e in exts}:
                return category

    # 2. Built-in categories
    for category, extensions in CATEGORY_EXTENSIONS.items():
        if ext in extensions:
            return category

    return DEFAULT_CATEGORY


def resolve_download_folder(
    base_dir: str | Path,
    name_or_url: Optional[str] = None,
    use_smart_folders: bool = True,
    smart_folder_name: str = SMART_FOLDER_NAME,
    custom_categories: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Determine target save directory for a download.

    If use_smart_folders is False or no name_or_url is provided:
        Returns Path(base_dir).

    If use_smart_folders is True:
        Returns Path(base_dir) / smart_folder_name / <Category>.
        Custom categories (if supplied) are resolved before built-ins.
    """
    base = Path(base_dir).resolve()
    if not use_smart_folders or not name_or_url:
        return base

    category = get_file_category(name_or_url, custom_categories=custom_categories)
    folder = base / smart_folder_name / category
    return folder


# ---------------------------------------------------------------------------
# Persistent Application Settings
# ---------------------------------------------------------------------------

def get_default_settings() -> Dict[str, Any]:
    """Default settings dictionary — backward-compatible; new keys carry safe defaults."""
    return {
        # ── Downloads ──────────────────────────────────────────────────────
        "dest_dir": str(get_default_download_dir()),
        "use_smart_folders": True,
        "smart_folder_name": SMART_FOLDER_NAME,
        "file_conflict_policy": "rename",   # "rename" | "prompt" | "skip" | "overwrite"
        "auto_start": True,
        "custom_categories": {},            # {"3D Models": ["stl","obj","fbx"], ...}
        # ── Connection ────────────────────────────────────────────────────
        "max_concurrent": 2,
        "num_connections": 6,
        "chunk_threshold_mb": 50,           # min file size for multi-chunk (MB)
        "speed_limit_dl_mbps": 0,           # 0 = unlimited
        "speed_limit_ul_kbps": 0,
        # ── General / System ──────────────────────────────────────────────
        "minimize_to_tray": True,
        "run_on_startup": False,
        "close_action": "tray",             # "tray" | "exit" | "ask"
        "on_complete_action": "notify",     # "nothing" | "notify" | "open_folder" | "open_file" | "chime"
        # ── BitTorrent ────────────────────────────────────────────────────
        "torrent_port": 6881,
        "torrent_random_port": False,
        "seeding_ratio_limit": 1.0,
        "dht_enabled": True,
        "pex_enabled": True,
        "lsd_enabled": True,
        "protocol_encryption": "enabled",   # "enabled" | "required" | "disabled"
        # ── Network / Proxy ───────────────────────────────────────────────
        "proxy_mode": "none",               # "none" | "system" | "manual"
        "proxy_host": "",
        "proxy_port": 8080,
        "proxy_username": "",
        "proxy_password": "",
        "proxy_type": "http",               # "http" | "socks5"
        "bridge_port": 8992,
        "max_retries": 5,
        "retry_backoff": 5,                 # seconds
        # ── Updates ───────────────────────────────────────────────────────
        "auto_check_updates": True,
        "update_channel": "stable",         # "stable" | "prerelease"
        "last_update_check_ts": 0.0,
    }


def load_settings() -> Dict[str, Any]:
    """Load settings from ~/.smart_download_manager/settings.json or return defaults."""
    defaults = get_default_settings()
    if not CONFIG_FILE.exists():
        return defaults

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                defaults.update(data)
                # Verify dest_dir exists or is valid
                if not defaults.get("dest_dir"):
                    defaults["dest_dir"] = str(get_default_download_dir())
    except Exception as exc:
        log.warning(f"Failed to read settings from {CONFIG_FILE}: {exc}")

    return defaults


def save_settings(settings: Dict[str, Any]) -> bool:
    """Persist settings to ~/.smart_download_manager/settings.json atomically."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = CONFIG_FILE.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        tmp_file.replace(CONFIG_FILE)
        return True
    except Exception as exc:
        log.error(f"Failed to save settings to {CONFIG_FILE}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Windows Startup Registry Helper
# ---------------------------------------------------------------------------

_STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_VALUE_NAME = "SmartDownloadManager"


def set_run_on_startup(enabled: bool) -> bool:
    """
    Add or remove the application from the Windows startup registry key
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.

    Returns True on success, False if the platform is not Windows or on error.
    """
    if sys.platform != "win32":
        log.debug("set_run_on_startup: not on Windows, skipping.")
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _STARTUP_REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                # Use the executable path; sys.executable when running from source,
                # or the frozen exe path when compiled with PyInstaller.
                exe_path = sys.executable if getattr(sys, "frozen", False) else sys.executable
                winreg.SetValueEx(key, _STARTUP_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
                log.info(f"Startup registry entry set: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, _STARTUP_VALUE_NAME)
                    log.info("Startup registry entry removed.")
                except FileNotFoundError:
                    pass  # Already absent
        return True
    except Exception as exc:
        log.error(f"Failed to modify startup registry: {exc}")
        return False


def get_run_on_startup() -> bool:
    """Check whether the startup registry entry currently exists."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _STARTUP_REG_KEY,
            0,
            winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, _STARTUP_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
