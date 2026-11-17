"""
Smart Download Manager — torrent_engine.py

BitTorrent & Magnet Link Download Engine wrapping libtorrent 2.x.
Features:
  • High-performance BitTorrent session management with DHT, PeX, and LSD
  • Full support for magnet:?xt=urn:btih:... URIs and .torrent files
  • Non-blocking metadata download with peer/seed discovery for magnet links
  • Fastresume state persistence (.fastresume) for seamless pausing and resumption
  • Unified callbacks compatible with QueueManager and Desktop GUI:
      - downloaded_bytes, total_bytes, speed, peers, seeds, status_msg
  • Clean cancellation via threading.Event without partial data corruption
  • Rich terminal progress display for CLI mode
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import libtorrent as lt
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from downloader import DownloadResult, DownloadStatus

log = logging.getLogger(__name__)
console = Console()

# ---------------------------------------------------------------------------
# Default High-Availability Public Trackers & DHT Routers
# ---------------------------------------------------------------------------

DEFAULT_TRACKERS: List[str] = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://explodie.org:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
]

DEFAULT_DHT_BOOTSTRAP_NODES = (
    "router.bittorrent.com:6881,"
    "dht.transmissionbt.com:6881,"
    "router.utorrent.com:6881"
)

DEFAULT_LISTEN_PORT = 6881


# ---------------------------------------------------------------------------
# Helper Functions: Magnet URI & Torrent Source Utilities
# ---------------------------------------------------------------------------

def is_torrent_source(source: str) -> bool:
    """
    Check if a given string represents a BitTorrent source:
    - magnet:?xt=urn:btih:... URI
    - Local path to a .torrent file
    - URL ending with .torrent
    """
    if not source:
        return False
    s = source.strip()
    if s.startswith("magnet:"):
        return True
    if s.lower().endswith(".torrent"):
        return True
    # Check if existing local file is .torrent
    try:
        p = Path(s)
        if p.is_file() and p.suffix.lower() == ".torrent":
            return True
    except Exception:
        pass
    return False


def parse_magnet_info_hash(magnet_uri: str) -> Optional[str]:
    """Extract hexadecimal or base32 info hash from a magnet link."""
    if not magnet_uri.startswith("magnet:"):
        return None
    try:
        query = magnet_uri.split("?", 1)[1] if "?" in magnet_uri else ""
        qs = parse_qs(query)
        xts = qs.get("xt", [])
        for xt in xts:
            if "urn:btih:" in xt.lower():
                return xt.split(":")[-1].lower()
    except Exception as exc:
        log.debug(f"Failed to extract info_hash from magnet: {exc}")
    return None


def parse_magnet_display_name(magnet_uri: str) -> Optional[str]:
    """Extract display name (dn parameter) from a magnet link."""
    if not magnet_uri.startswith("magnet:"):
        return None
    try:
        query = magnet_uri.split("?", 1)[1] if "?" in magnet_uri else ""
        qs = parse_qs(query)
        dns = qs.get("dn", [])
        if dns and dns[0]:
            return unquote(dns[0])
    except Exception as exc:
        log.debug(f"Failed to extract dn from magnet: {exc}")
    return None


def get_fastresume_path(dest_dir: Path | str, info_hash: str) -> Path:
    """Return the path to the .fastresume file for a given info hash."""
    dest = Path(dest_dir).resolve()
    resume_dir = dest / ".fastresume"
    resume_dir.mkdir(parents=True, exist_ok=True)
    return resume_dir / f"{info_hash.lower()}.fastresume"


# ---------------------------------------------------------------------------
# Session Manager (Singleton / Lifecycle Controller)
# ---------------------------------------------------------------------------

class TorrentSessionManager:
    """
    Manages a shared libtorrent session with DHT, PeX, and LSD enabled.
    Ensures optimal peer discovery, single-port binding, and clean shutdown.
    """

    _instance: Optional[TorrentSessionManager] = None
    _lock = threading.Lock()

    def __init__(
        self,
        listen_port: int = DEFAULT_LISTEN_PORT,
        enable_dht: bool = True,
        enable_lsd: bool = True,
    ):
        self.listen_port = listen_port
        self.enable_dht = enable_dht
        self.enable_lsd = enable_lsd

        settings = {
            "listen_interfaces": f"0.0.0.0:{listen_port},[::]:{listen_port}",
            "listen_system_port_fallback": True,
            "enable_dht": self.enable_dht,
            "enable_lsd": self.enable_lsd,
            "dht_bootstrap_nodes": DEFAULT_DHT_BOOTSTRAP_NODES,
            "alert_mask": (
                lt.alert.category_t.error_notification
                | lt.alert.category_t.status_notification
                | lt.alert.category_t.storage_notification
            ),
        }

        self.session = lt.session(settings)

        # Register standard BitTorrent extensions (PeX & Metadata)
        try:
            self.session.add_extension(lt.create_ut_pex_plugin)
        except Exception as exc:
            log.debug(f"PeX extension note: {exc}")

        try:
            self.session.add_extension(lt.create_ut_metadata_plugin)
        except Exception as exc:
            log.debug(f"Metadata extension note: {exc}")

        log.info(
            f"TorrentSessionManager initialized (listen_port={self.session.listen_port()}, "
            f"dht={self.enable_dht}, lsd={self.enable_lsd})"
        )

    @classmethod
    def get_instance(cls) -> TorrentSessionManager:
        """Get or initialize the shared singleton session manager."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = TorrentSessionManager()
            return cls._instance

    def add_torrent(self, params: lt.add_torrent_params) -> lt.torrent_handle:
        """Add a torrent to the session and return its handle."""
        return self.session.add_torrent(params)

    def remove_torrent(self, handle: lt.torrent_handle, delete_files: bool = False) -> None:
        """Remove a torrent from the session without touching files unless specified."""
        if handle.is_valid():
            try:
                flags = lt.session.delete_files if delete_files else 0
                self.session.remove_torrent(handle, flags)
            except Exception as exc:
                log.debug(f"Error removing torrent handle: {exc}")

    def save_resume_data_sync(
        self,
        handle: lt.torrent_handle,
        fastresume_path: Path,
        timeout: float = 3.0,
    ) -> bool:
        """
        Request fastresume data for a handle and block until generated or timed out.
        Writes binary fastresume buffer directly to disk.
        """
        if not handle.is_valid():
            return False

        try:
            handle.save_resume_data(lt.save_resume_flags_t.only_if_modified)
        except Exception:
            try:
                handle.save_resume_data()
            except Exception as exc:
                log.debug(f"save_resume_data call failed: {exc}")
                return False

        start_t = time.time()
        while time.time() - start_t < timeout:
            alerts = self.session.pop_alerts()
            for alert in alerts:
                if isinstance(alert, lt.save_resume_data_alert) and alert.handle == handle:
                    try:
                        buf = lt.write_resume_data_buf(alert.params)
                        fastresume_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(fastresume_path, "wb") as f:
                            f.write(buf)
                        log.info(f"Fastresume saved ({len(buf)} bytes) -> {fastresume_path.name}")
                        return True
                    except Exception as exc:
                        log.warning(f"Failed to serialize fastresume data: {exc}")
                        return False
                elif isinstance(alert, lt.save_resume_data_failed_alert) and alert.handle == handle:
                    log.warning(f"save_resume_data_failed: {alert.message()}")
                    return False
            time.sleep(0.03)

        return False


# ---------------------------------------------------------------------------
# Core Torrent Download Function
# ---------------------------------------------------------------------------

def download_torrent(
    source: str,
    dest_dir: str = "downloads",
    filename: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
    save_fastresume: bool = True,
    show_terminal_progress: bool = False,
    seed_after_complete: bool = False,
    session: Optional[lt.session] = None,
) -> DownloadResult:
    """
    Download a BitTorrent source (magnet URI or .torrent file).

    Args:
        source: Magnet URI or path to .torrent file
        dest_dir: Output folder for downloaded files
        filename: Optional override filename
        progress_callback: Callable receiving (downloaded, total, speed, status_msg, peers, seeds)
        cancel_event: Event to trigger clean pause / abort
        save_fastresume: Whether to persist .fastresume state
        show_terminal_progress: Whether to render Rich progress bar
        seed_after_complete: If True, stays in seeding state; if False, stops at 100%
        session: Optional custom libtorrent.session (uses TorrentSessionManager if None)

    Returns:
        DownloadResult compatible with downloader.py
    """
    out_dir = Path(dest_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mgr = TorrentSessionManager.get_instance() if session is None else None
    ses = mgr.session if mgr else session

    if ses is None:
        return DownloadResult(
            status=DownloadStatus.FAILED,
            path=out_dir / (filename or "torrent_download"),
            error="No active libtorrent session available",
        )

    # 1. Determine Info Hash & Fastresume
    info_hash_str: Optional[str] = None
    if source.startswith("magnet:"):
        info_hash_str = parse_magnet_info_hash(source)
    elif Path(source).is_file():
        try:
            ti = lt.torrent_info(str(Path(source).resolve()))
            info_hash_str = str(ti.info_hash()).lower()
        except Exception as exc:
            log.warning(f"Could not inspect .torrent file: {exc}")

    fastresume_file: Optional[Path] = None
    if info_hash_str and save_fastresume:
        fastresume_file = get_fastresume_path(out_dir, info_hash_str)

    # Clean up prior instance in session if it had a different save_path
    if info_hash_str:
        for existing_h in ses.get_torrents():
            if existing_h.is_valid() and str(existing_h.info_hash()).lower() == info_hash_str.lower():
                try:
                    if Path(existing_h.status().save_path).resolve() != out_dir:
                        log.info(f"Removing prior instance of {info_hash_str} with different save_path")
                        ses.remove_torrent(existing_h, 0)
                        time.sleep(0.05)
                except Exception:
                    pass

    # 2. Build add_torrent_params (from fastresume or source)
    atp: Optional[lt.add_torrent_params] = None
    if fastresume_file and fastresume_file.is_file():
        try:
            with open(fastresume_file, "rb") as rf:
                buf = rf.read()
            atp = lt.read_resume_data(buf)
            atp.save_path = str(out_dir)
            log.info(f"Loaded existing fastresume state: {fastresume_file.name}")
        except Exception as exc:
            log.warning(f"Error loading fastresume {fastresume_file}: {exc}; starting fresh.")
            atp = None

    if atp is None:
        if source.startswith("magnet:"):
            try:
                atp = lt.parse_magnet_uri(source)
                atp.save_path = str(out_dir)
                # Supplement with default trackers
                trackers = list(atp.trackers)
                for tr in DEFAULT_TRACKERS:
                    if tr not in trackers:
                        trackers.append(tr)
                atp.trackers = trackers
            except Exception as exc:
                return DownloadResult(
                    status=DownloadStatus.FAILED,
                    path=out_dir / (filename or "torrent_download"),
                    error=f"Failed to parse magnet link: {exc}",
                )
        else:
            # .torrent file on disk or web URL
            torrent_path = Path(source)
            if not torrent_path.is_file():
                # Handle possible remote .torrent URL
                if source.startswith("http://") or source.startswith("https://"):
                    import urllib.request
                    temp_torrent = out_dir / f"temp_{int(time.time())}.torrent"
                    try:
                        urllib.request.urlretrieve(source, str(temp_torrent))
                        torrent_path = temp_torrent
                    except Exception as exc:
                        return DownloadResult(
                            status=DownloadStatus.FAILED,
                            path=out_dir / (filename or "torrent_download"),
                            error=f"Failed to download remote .torrent: {exc}",
                        )
                else:
                    return DownloadResult(
                        status=DownloadStatus.FAILED,
                        path=out_dir / (filename or "torrent_download"),
                        error=f"Torrent file not found: {source}",
                    )

            try:
                ti = lt.torrent_info(str(torrent_path.resolve()))
                atp = lt.add_torrent_params()
                atp.ti = ti
                atp.save_path = str(out_dir)
            except Exception as exc:
                return DownloadResult(
                    status=DownloadStatus.FAILED,
                    path=out_dir / (filename or "torrent_download"),
                    error=f"Failed to read torrent file: {exc}",
                )

    if cancel_event and cancel_event.is_set():
        return DownloadResult(
            status=DownloadStatus.CANCELLED,
            path=out_dir / (filename or "torrent_download"),
            bytes_downloaded=0,
        )

    # 3. Add to libtorrent session
    try:
        handle: lt.torrent_handle = ses.add_torrent(atp)
    except Exception as exc:
        return DownloadResult(
            status=DownloadStatus.FAILED,
            path=out_dir / (filename or "torrent_download"),
            error=f"Failed to add torrent to session: {exc}",
        )

    if not handle.is_valid():
        return DownloadResult(
            status=DownloadStatus.FAILED,
            path=out_dir / (filename or "torrent_download"),
            error="Failed to create valid torrent handle",
        )

    # Derive initial target path
    display_title = filename
    if not display_title and source.startswith("magnet:"):
        display_title = parse_magnet_display_name(source) or (
            f"magnet-{info_hash_str[:8]}" if info_hash_str else "torrent_download"
        )
    elif not display_title and hasattr(atp, "ti") and atp.ti:
        display_title = atp.ti.name()
    elif not display_title:
        display_title = Path(source).stem

    target_path = out_dir / display_title

    # 4. Progress Tracking Setup
    def _fire_cb(dl_bytes: int, tot_bytes: Optional[int], spd: float, msg: str, peers: int, seeds: int):
        if progress_callback:
            try:
                progress_callback(dl_bytes, tot_bytes, spd, msg, peers, seeds)
            except TypeError:
                progress_callback(dl_bytes, tot_bytes, spd, msg)

    rich_progress = None
    task_id = None
    if show_terminal_progress:
        rich_progress = Progress(
            TextColumn("[bold cyan]{task.fields[name]}[/]"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TextColumn("[dim]{task.fields[status]}[/]"),
            "•",
            TimeRemainingColumn(),
            console=console,
        )
        rich_progress.start()
        task_id = rich_progress.add_task(
            "download",
            total=None,
            completed=0,
            name=display_title,
            status="Connecting...",
        )

    # 5. Main Download Loop
    try:
        last_progress_update = 0.0

        while True:
            # Check user cancellation event
            if cancel_event and cancel_event.is_set():
                log.info(f"Cancellation requested for torrent {display_title}")
                s = handle.status()
                # Save fastresume if enabled
                if fastresume_file and mgr:
                    mgr.save_resume_data_sync(handle, fastresume_file)
                handle.pause()
                try:
                    ses.remove_torrent(handle, 0)
                except Exception:
                    pass
                _fire_cb(s.total_done, s.total_wanted, 0.0, "Paused", s.num_peers, s.num_seeds)
                return DownloadResult(
                    status=DownloadStatus.CANCELLED,
                    path=target_path,
                    bytes_downloaded=s.total_done,
                    total_size=s.total_wanted if s.total_wanted > 0 else None,
                )

            # Query current status
            s = handle.status()

            # Resolve metadata once available
            if s.has_metadata:
                ti = s.torrent_file
                if ti and ti.is_valid():
                    real_name = ti.name()
                    if not filename:
                        target_path = out_dir / real_name
                        display_title = real_name
                    if not info_hash_str:
                        info_hash_str = str(ti.info_hash()).lower()
                        if save_fastresume:
                            fastresume_file = get_fastresume_path(out_dir, info_hash_str)

            total_bytes = s.total_wanted if s.total_wanted > 0 else (s.total if s.total > 0 else None)
            downloaded_bytes = s.total_done
            speed = float(s.download_rate)
            peers = s.num_peers
            seeds = s.num_seeds

            # Human status description
            if not s.has_metadata:
                status_msg = f"Fetching metadata ({peers} peers)"
            elif s.state == lt.torrent_status.states.checking_files:
                status_msg = f"Checking files ({s.progress * 100:.1f}%)"
            elif s.state == lt.torrent_status.states.checking_resume_data:
                status_msg = "Checking resume data..."
            elif s.is_seeding or s.state in (lt.torrent_status.states.finished, lt.torrent_status.states.seeding):
                status_msg = f"Complete (Seeding · {peers} peers · {seeds} seeds)"
            elif s.state == lt.torrent_status.states.downloading:
                spd_fmt = f"{speed / (1024 * 1024):.1f} MB/s" if speed >= 1024 * 1024 else f"{speed / 1024:.0f} KB/s"
                status_msg = f"⚡ Downloading ({spd_fmt} · {peers} peers · {seeds} seeds)"
            else:
                status_msg = f"Status: {s.state}"

            # Check fatal error
            if s.errc and s.errc.value() != 0:
                err_msg = s.error or s.errc.message()
                log.error(f"Torrent error for {display_title}: {err_msg}")
                return DownloadResult(
                    status=DownloadStatus.FAILED,
                    path=target_path,
                    bytes_downloaded=downloaded_bytes,
                    total_size=total_bytes,
                    error=err_msg,
                )

            # Fire callback
            now = time.time()
            if now - last_progress_update >= 0.15:
                last_progress_update = now
                _fire_cb(downloaded_bytes, total_bytes, speed, status_msg, peers, seeds)

                if rich_progress and task_id is not None:
                    rich_progress.update(
                        task_id,
                        total=total_bytes,
                        completed=downloaded_bytes,
                        name=display_title,
                        status=status_msg,
                    )

            # Check completion criteria
            is_finished = (
                s.is_seeding
                or s.state in (lt.torrent_status.states.finished, lt.torrent_status.states.seeding)
                or (s.has_metadata and total_bytes is not None and downloaded_bytes >= total_bytes and total_bytes > 0)
            )

            if is_finished:
                log.info(f"Torrent {display_title} download complete! ({downloaded_bytes:,} bytes)")
                if fastresume_file and mgr:
                    mgr.save_resume_data_sync(handle, fastresume_file)

                _fire_cb(downloaded_bytes, total_bytes, 0.0, "Complete", peers, seeds)
                if rich_progress and task_id is not None:
                    rich_progress.update(
                        task_id,
                        completed=total_bytes or downloaded_bytes,
                        status="[green]Done[/]",
                    )

                if not seed_after_complete:
                    handle.pause()
                    try:
                        ses.remove_torrent(handle, 0)
                    except Exception:
                        pass

                return DownloadResult(
                    status=DownloadStatus.COMPLETED,
                    path=target_path,
                    bytes_downloaded=downloaded_bytes,
                    total_size=total_bytes or downloaded_bytes,
                )

            time.sleep(0.2)

    except Exception as exc:
        log.error(f"Unexpected exception during torrent download: {exc}", exc_info=True)
        return DownloadResult(
            status=DownloadStatus.FAILED,
            path=target_path,
            bytes_downloaded=0,
            error=str(exc),
        )

    finally:
        if rich_progress:
            rich_progress.stop()
