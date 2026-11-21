"""
Smart Download Manager — queue_manager.py

Background Download Queue & Batch Processing Engine.
Features:
  • Concurrent & sequential task processing with configurable worker limits
  • Batch file ingestion (urls.txt) with flexible formats:
      - URL
      - URL | filename
      - URL | filename | referer
  • Automatic skipping of already-completed files (size match / HTTP 416)
  • Non-blocking expired URL (HTTP 401/403/410) handling:
      - Marks item EXPIRED and preserves partial state
      - Automatically proceeds with remaining queue items
  • Live progress tracking per item (bytes, speed, ETA)
  • Comprehensive batch summary report generator
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import browser_session
from browser_session import get_browser_session, make_session_headers
from downloader import (
    DEFAULT_NUM_CONNECTIONS,
    MULTI_CHUNK_MIN_SIZE,
    DownloadResult,
    DownloadStatus,
    download,
    filename_from_url,
    infer_referer,
    probe_server,
)
from state import DownloadManifest
from torrent_engine import (
    download_torrent,
    is_torrent_source,
    parse_magnet_display_name,
    parse_magnet_info_hash,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and Data Models
# ---------------------------------------------------------------------------

class QueueItemStatus(Enum):
    """Lifecycle states of an item in the download queue."""
    QUEUED = "queued"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"          # Already completed on disk
    EXPIRED = "expired"          # HTTP 403 / 410 signed URL expired
    PAUSED = "paused"            # Manually paused by user
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QueueItem:
    """Represents a single download task inside the Queue Manager."""
    url: str
    filename: Optional[str] = None
    referer: Optional[str] = None
    dest_dir: str = "downloads"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: QueueItemStatus = QueueItemStatus.QUEUED
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed: float = 0.0
    status_msg: str = "Queued"
    error: Optional[str] = None
    target_path: Optional[Path] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    result: Optional[DownloadResult] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    is_skipped: bool = False
    peers: int = 0
    seeds: int = 0

    @property
    def is_torrent_task(self) -> bool:
        """Check if this queue item is a BitTorrent download."""
        u = self.url.strip()
        return is_torrent_source(u) or (self.filename is not None and self.filename.endswith(".torrent"))

    @property
    def display_name(self) -> str:
        """Friendly name for display."""
        if self.filename:
            return self.filename
        if self.url.startswith("magnet:"):
            dn = parse_magnet_display_name(self.url)
            if dn:
                return dn
            h = parse_magnet_info_hash(self.url)
            if h:
                return f"magnet-{h[:10]}"
            return "magnet-download"
        return filename_from_url(self.url)

    @property
    def progress_fraction(self) -> float:
        """Return 0.0 to 1.0 download progress fraction."""
        if self.status in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED):
            return 1.0
        if self.total_bytes and self.total_bytes > 0:
            return min(1.0, max(0.0, self.downloaded_bytes / self.total_bytes))
        return 0.0

    @property
    def formatted_speed(self) -> str:
        """Human-readable speed string."""
        if self.speed <= 0:
            return "0 B/s"
        elif self.speed < 1024:
            return f"{self.speed:.0f} B/s"
        elif self.speed < 1024 * 1024:
            return f"{self.speed / 1024:.1f} KB/s"
        else:
            return f"{self.speed / (1024 * 1024):.1f} MB/s"

    @property
    def formatted_size(self) -> str:
        """Formatted downloaded / total bytes."""
        def _fmt(b: int) -> str:
            if b < 1024:
                return f"{b} B"
            elif b < 1024 * 1024:
                return f"{b / 1024:.1f} KB"
            elif b < 1024 * 1024 * 1024:
                return f"{b / (1024 * 1024):.1f} MB"
            return f"{b / (1024 * 1024 * 1024):.2f} GB"

        cur = _fmt(self.downloaded_bytes)
        if self.total_bytes and self.total_bytes > 0:
            return f"{cur} / {_fmt(self.total_bytes)}"
        return cur


@dataclass
class BatchSummary:
    """Summary metrics of a batch execution."""
    total_items: int = 0
    completed: int = 0
    skipped: int = 0
    expired: int = 0
    failed: int = 0
    cancelled: int = 0
    total_bytes_downloaded: int = 0
    duration: float = 0.0
    items: List[QueueItem] = field(default_factory=list)

    def print_report(self, console: Optional[Console] = None) -> None:
        """Print a polished Rich summary table to console."""
        con = console or Console()

        con.print("\n")
        title = "📊 Batch Download Summary Report"
        con.print(Panel(
            f"[bold]Total Tasks:[/] {self.total_items}   "
            f"[bold green]✔ Completed:[/] {self.completed}   "
            f"[bold cyan]⏩ Skipped:[/] {self.skipped}   "
            f"[bold yellow]⚠️ Expired (403):[/] {self.expired}   "
            f"[bold red]❌ Failed:[/] {self.failed}\n"
            f"[bold]Total Data:[/] {self._format_bytes(self.total_bytes_downloaded)}   "
            f"[bold]Duration:[/] {self.duration:.1f}s",
            title=f"[bold cyan]{title}[/]",
            border_style="cyan",
        ))

        table = Table(title="Batch Item Details", show_header=True, header_style="bold magenta")
        table.add_column("#", width=4, justify="right")
        table.add_column("Filename", style="bold", min_width=20)
        table.add_column("Status", width=14)
        table.add_column("Progress", width=22)
        table.add_column("Notes / Details", min_width=24)

        for idx, it in enumerate(self.items, 1):
            if it.status == QueueItemStatus.COMPLETED:
                st_str = "[bold green]✔ Completed[/]"
                note = "Saved successfully"
            elif it.status == QueueItemStatus.SKIPPED:
                st_str = "[bold cyan]⏩ Skipped[/]"
                note = "Already complete on disk"
            elif it.status == QueueItemStatus.EXPIRED:
                st_str = "[bold yellow]⚠️ Expired[/]"
                note = "HTTP 403 signed link expired (state saved)"
            elif it.status == QueueItemStatus.FAILED:
                st_str = "[bold red]❌ Failed[/]"
                note = it.error or "Error occurred"
            elif it.status == QueueItemStatus.CANCELLED or it.status == QueueItemStatus.PAUSED:
                st_str = "[dim yellow]⏸ Paused[/]"
                note = "Manually paused"
            else:
                st_str = f"[dim]{it.status.value}[/]"
                note = it.status_msg

            table.add_row(
                str(idx),
                it.display_name,
                st_str,
                it.formatted_size,
                note,
            )

        con.print(table)

        if self.expired > 0:
            con.print(
                "\n[bold yellow]💡 Tip:[/] Some items hit expired links (HTTP 403). "
                "Their partial bytes are completely safe!\n"
                "   Resume them anytime by providing a fresh URL in the GUI or via:\n"
                "   [cyan]python __main__.py -u <filename>[/]\n"
            )

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        if num_bytes < 1024:
            return f"{num_bytes} B"
        elif num_bytes < 1024 * 1024:
            return f"{num_bytes / 1024:.1f} KB"
        elif num_bytes < 1024 * 1024 * 1024:
            return f"{num_bytes / (1024 * 1024):.1f} MB"
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


# ---------------------------------------------------------------------------
# Batch File Parser
# ---------------------------------------------------------------------------

def parse_urls_file(
    file_path: str | Path,
    default_dest: str = "downloads",
) -> List[QueueItem]:
    """
    Parse a batch URLs file (e.g. urls.txt).

    Supported line formats:
      1. URL
      2. URL | filename
      3. URL | filename | referer

    Lines starting with '#' or empty lines are ignored.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"URLs file not found: {path}")

    items: List[QueueItem] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line_num, raw_line in enumerate(fh, 1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            parts = [p.strip().strip('"\'') for p in line.split("|")]
            url = parts[0]
            if not (
                url.startswith("http://")
                or url.startswith("https://")
                or is_torrent_source(url)
            ):
                log.warning(f"Line {line_num}: Skipping invalid URL or torrent source '{url}'")
                continue

            filename: Optional[str] = None
            referer: Optional[str] = None

            if len(parts) >= 2 and parts[1]:
                filename = parts[1]
            if len(parts) >= 3 and parts[2]:
                referer = parts[2]

            items.append(
                QueueItem(
                    url=url,
                    filename=filename,
                    referer=referer,
                    dest_dir=default_dest,
                )
            )

    return items


# ---------------------------------------------------------------------------
# Background Download Queue Manager
# ---------------------------------------------------------------------------

class QueueManager:
    """
    Thread-safe background queue manager for batch and sequential downloads.
    Supports concurrency limits, pausing, resume, skip detection, and 403 handling.
    """

    def __init__(
        self,
        dest_dir: str = "downloads",
        max_concurrent: int = 2,
        num_connections: int = DEFAULT_NUM_CONNECTIONS,
        min_chunk_size: int = MULTI_CHUNK_MIN_SIZE,
        on_item_updated: Optional[Callable[[QueueItem], None]] = None,
        on_item_completed: Optional[Callable[[QueueItem], None]] = None,
        on_queue_completed: Optional[Callable[[BatchSummary], None]] = None,
        state_file: Optional[Path | str] = None,
        persist_state: bool = False,
    ):
        self.dest_dir = dest_dir
        self.max_concurrent = max(1, max_concurrent)
        self.num_connections = num_connections
        self.min_chunk_size = min_chunk_size

        self.on_item_updated = on_item_updated
        self.on_item_completed = on_item_completed
        self.on_queue_completed = on_queue_completed

        self.state_file = Path(state_file) if state_file else (Path(dest_dir) / ".queue_state.json")
        self.persist_state = persist_state

        self.items: List[QueueItem] = []
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._is_running = False
        self._is_paused = False
        self._stop_event = threading.Event()
        self._coordinator_thread: Optional[threading.Thread] = None
        self._active_workers: Dict[str, threading.Thread] = {}
        self._start_time: float = 0.0

        if self.persist_state:
            self._load_state()

    def _load_state(self) -> None:
        """Restore persisted download tasks across application restarts."""
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return
            with self._lock:
                for d in data:
                    status_val = d.get("status", "paused")
                    if status_val in ("active", "queued"):
                        status_val = "paused"
                    try:
                        status_enum = QueueItemStatus(status_val)
                    except ValueError:
                        status_enum = QueueItemStatus.PAUSED

                    item = QueueItem(
                        url=d.get("url", ""),
                        filename=d.get("filename"),
                        referer=d.get("referer"),
                        dest_dir=d.get("dest_dir", self.dest_dir),
                        id=d.get("id", uuid.uuid4().hex[:8]),
                        status=status_enum,
                        downloaded_bytes=d.get("downloaded_bytes", 0),
                        total_bytes=d.get("total_bytes"),
                        created_at=d.get("created_at", time.time()),
                        completed_at=d.get("completed_at"),
                        error=d.get("error"),
                    )
                    if status_enum == QueueItemStatus.PAUSED:
                        item.status_msg = "Paused · Ready to resume"
                    elif status_enum == QueueItemStatus.COMPLETED:
                        item.status_msg = "Complete"
                    elif status_enum == QueueItemStatus.EXPIRED:
                        item.status_msg = "Link Expired (403)"
                    elif status_enum == QueueItemStatus.SKIPPED:
                        item.status_msg = "Skipped"

                    target_dir = Path(item.dest_dir)
                    fname = item.filename or (filename_from_url(item.url) if item.url else "download")
                    target = target_dir / fname
                    item.target_path = target

                    # Probe manifest on disk to sync accurate state
                    meta_path = target.parent / f"{target.name}.meta.json"
                    if meta_path.exists():
                        try:
                            mf = DownloadManifest.load(meta_path)
                            if mf:
                                if mf.latest_url:
                                    item.url = mf.latest_url
                                if mf.total_bytes:
                                    item.total_bytes = mf.total_bytes
                                if mf.downloaded_bytes:
                                    item.downloaded_bytes = mf.downloaded_bytes
                        except Exception:
                            pass
                    elif target.exists():
                        item.downloaded_bytes = target.stat().st_size

                    self.items.append(item)
            log.info(f"Restored {len(self.items)} queue items from {self.state_file}")
        except Exception as exc:
            log.warning(f"Failed to load queue state from {self.state_file}: {exc}")

    def save_state(self) -> None:
        """Persist current queue tasks atomically to disk."""
        if not self.persist_state:
            return
        with self._save_lock:
            with self._lock:
                data = []
                for it in self.items:
                    status_str = it.status.value
                    if status_str in ("active", "queued"):
                        status_str = "paused"
                    data.append({
                        "id": it.id,
                        "url": it.url,
                        "filename": it.filename,
                        "referer": it.referer,
                        "dest_dir": it.dest_dir,
                        "status": status_str,
                        "downloaded_bytes": it.downloaded_bytes,
                        "total_bytes": it.total_bytes,
                        "created_at": it.created_at,
                        "completed_at": it.completed_at,
                        "error": it.error,
                    })
            tmp_file = None
            try:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_file = self.state_file.with_name(f"{self.state_file.name}.{uuid.uuid4().hex[:6]}.tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                tmp_file.replace(self.state_file)
            except Exception as exc:
                log.warning(f"Failed to save queue state to {self.state_file}: {exc}")
                if tmp_file and tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except Exception:
                        pass

    # ── Queue Item Management ─────────────────────────────────────────

    def add_item(
        self,
        url: str,
        filename: Optional[str] = None,
        referer: Optional[str] = None,
        dest_dir: Optional[str] = None,
    ) -> QueueItem:
        """Add a single URL to the queue."""
        item = QueueItem(
            url=url,
            filename=filename,
            referer=referer,
            dest_dir=dest_dir or self.dest_dir,
        )
        with self._lock:
            self.items.append(item)
        log.info(f"Enqueued item: {item.display_name} [{item.id}]")
        self._notify_item_updated(item)
        self.save_state()
        return item

    def add_items_from_file(
        self,
        file_path: str | Path,
        dest_dir: Optional[str] = None,
    ) -> List[QueueItem]:
        """Parse batch file and append all items to the queue."""
        new_items = parse_urls_file(file_path, default_dest=dest_dir or self.dest_dir)
        with self._lock:
            self.items.extend(new_items)
        for item in new_items:
            self._notify_item_updated(item)
        self.save_state()
        return new_items

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        """Find item by ID."""
        with self._lock:
            for it in self.items:
                if it.id == item_id:
                    return it
        return None

    def pause_item(self, item_id: str) -> bool:
        """Pause a specific active or queued item."""
        with self._lock:
            item = self.get_item(item_id)
            if not item:
                return False
            if item.status == QueueItemStatus.QUEUED:
                item.status = QueueItemStatus.PAUSED
                item.status_msg = "Paused"
                self._notify_item_updated(item)
                self.save_state()
                return True
            elif item.status == QueueItemStatus.ACTIVE:
                item.cancel_event.set()
                item.status_msg = "Pausing..."
                self._notify_item_updated(item)
                self.save_state()
                return True
        return False

    def resume_item(self, item_id: str, fresh_url: Optional[str] = None) -> bool:
        """Resume a paused or expired item (optionally with a fresh URL)."""
        with self._lock:
            item = self.get_item(item_id)
            if not item:
                return False
            if fresh_url:
                item.url = fresh_url
            item.status = QueueItemStatus.QUEUED
            item.status_msg = "Queued"
            item.error = None
            item.cancel_event = threading.Event()
            self._notify_item_updated(item)
            self.save_state()
        return True

    def update_item_url(self, item_id: str, fresh_url: str) -> bool:
        """Update URL of an expired or paused item and mark ready for resume."""
        return self.resume_item(item_id, fresh_url=fresh_url)

    def remove_item(self, item_id: str) -> bool:
        """Remove item from queue (pauses if currently active)."""
        with self._lock:
            item = self.get_item(item_id)
            if not item:
                return False
            if item.status == QueueItemStatus.ACTIVE:
                item.cancel_event.set()
            self.items = [it for it in self.items if it.id != item_id]
            self.save_state()
        return True

    def clear_completed(self) -> None:
        """Remove all COMPLETED and SKIPPED items from the queue."""
        with self._lock:
            self.items = [
                it for it in self.items
                if it.status not in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED)
            ]
            self.save_state()

    # ── Queue Lifecycle Controls ──────────────────────────────────────

    def start(self) -> None:
        """Start or resume background queue processing."""
        with self._lock:
            self._is_paused = False
            self._stop_event.clear()
            if self._start_time == 0.0:
                self._start_time = time.time()

            if not self._is_running:
                self._is_running = True
                self._coordinator_thread = threading.Thread(
                    target=self._coordinator_loop,
                    name="QueueCoordinator",
                    daemon=True,
                )
                self._coordinator_thread.start()
                log.info(f"QueueManager started with max_concurrent={self.max_concurrent}")

    def pause(self) -> None:
        """Pause queue processing and signal active downloads to pause."""
        with self._lock:
            self._is_paused = True
            for item_id, it in list(self._active_workers.items()):
                it_obj = self.get_item(item_id)
                if it_obj:
                    it_obj.cancel_event.set()
        log.info("QueueManager paused.")

    def stop(self) -> None:
        """Permanently stop queue processing and abort all tasks."""
        with self._lock:
            self._stop_event.set()
            self._is_running = False
            self._is_paused = True
            for item in self.items:
                if item.status == QueueItemStatus.ACTIVE:
                    item.cancel_event.set()
            self.save_state()
        log.info("QueueManager stopped.")

    @property
    def is_running(self) -> bool:
        return self._is_running and not self._is_paused

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    # ── Coordinator Loop & Worker Dispatcher ──────────────────────────

    def _coordinator_loop(self) -> None:
        """Background coordinator that schedules tasks up to max_concurrent."""
        all_completed_notified = False

        while not self._stop_event.is_set():
            if self._is_paused:
                time.sleep(0.2)
                continue

            with self._lock:
                # Clean up finished worker threads
                finished_ids = [
                    iid for iid, th in self._active_workers.items() if not th.is_alive()
                ]
                for iid in finished_ids:
                    del self._active_workers[iid]

                current_active = len(self._active_workers)
                available_slots = self.max_concurrent - current_active

                # Find next queued items
                queued_items = [
                    it for it in self.items if it.status == QueueItemStatus.QUEUED
                ]

                if available_slots > 0 and queued_items:
                    all_completed_notified = False
                    for item in queued_items[:available_slots]:
                        item.status = QueueItemStatus.ACTIVE
                        item.status_msg = "Starting..."
                        item.cancel_event = threading.Event()
                        self._notify_item_updated(item)

                        th = threading.Thread(
                            target=self._download_worker,
                            args=(item,),
                            name=f"QueueWorker-{item.id}",
                            daemon=True,
                        )
                        self._active_workers[item.id] = th
                        th.start()

                # Check if all items in queue are in terminal state
                active_count = len(self._active_workers)
                has_pending = any(
                    it.status == QueueItemStatus.QUEUED for it in self.items
                )

                if active_count == 0 and not has_pending and len(self.items) > 0:
                    if not all_completed_notified:
                        all_completed_notified = True
                        summary = self.get_summary()
                        if self.on_queue_completed:
                            try:
                                self.on_queue_completed(summary)
                            except Exception as exc:
                                log.error(f"Error in on_queue_completed: {exc}")

            time.sleep(0.15)

        self._is_running = False

    # ── Download Worker Execution ─────────────────────────────────────

    def _download_worker(self, item: QueueItem) -> None:
        """Worker thread executing download for a single QueueItem."""
        try:
            out_dir = Path(item.dest_dir).resolve()
            out_dir.mkdir(parents=True, exist_ok=True)

            # ── Protocol Routing: BitTorrent vs HTTP ───────────────────
            if is_torrent_source(item.url):
                last_torrent_cb = 0.0
                def torrent_progress_cb(
                    downloaded: int,
                    total: Optional[int],
                    speed: float,
                    msg: str,
                    peers: int = 0,
                    seeds: int = 0,
                ):
                    nonlocal last_torrent_cb
                    item.downloaded_bytes = downloaded
                    if total:
                        item.total_bytes = total
                    item.speed = speed
                    item.status_msg = msg
                    item.peers = peers
                    item.seeds = seeds
                    now = time.time()
                    if now - last_torrent_cb >= 0.12:
                        last_torrent_cb = now
                        self._notify_item_updated(item)

                res = download_torrent(
                    source=item.url,
                    dest_dir=str(out_dir),
                    filename=item.filename,
                    progress_callback=torrent_progress_cb,
                    cancel_event=item.cancel_event,
                )

                item.result = res
                item.downloaded_bytes = res.bytes_downloaded
                if res.total_size:
                    item.total_bytes = res.total_size
                if res.path:
                    item.target_path = res.path
                    if not item.filename and res.path.name:
                        item.filename = res.path.name
                item.completed_at = time.time()

                if res.status == DownloadStatus.COMPLETED:
                    item.status = QueueItemStatus.COMPLETED
                    item.status_msg = "Complete"
                    item.speed = 0.0
                elif res.status == DownloadStatus.CANCELLED:
                    item.status = QueueItemStatus.PAUSED
                    item.status_msg = "Paused"
                    item.speed = 0.0
                else:
                    item.status = QueueItemStatus.FAILED
                    item.status_msg = "Failed"
                    item.error = res.error or "Torrent download failed"
                    item.speed = 0.0

                self._notify_item_updated(item)
                self._notify_item_completed(item)
                self.save_state()
                return

            # ── Standard HTTP(S) Workflow ─────────────────────────────
            filename = item.filename or filename_from_url(item.url)
            target_path = out_dir / filename
            item.target_path = target_path

            # 1. Harvest session headers
            session = get_browser_session(item.url)
            headers = make_session_headers(session)
            ref = infer_referer(item.url, item.referer)
            if ref:
                headers["Referer"] = ref

            # 2. Server capability probe & skip check
            probe = None
            try:
                probe = probe_server(item.url, headers=headers)
                if probe.filename and not item.filename:
                    item.filename = probe.filename
                    target_path = out_dir / probe.filename
                    item.target_path = target_path
                if probe.total_size:
                    item.total_bytes = probe.total_size
            except Exception as exc:
                # If probe fails due to 401/403/410, download() will catch it cleanly
                log.debug(f"Probe error for {item.url}: {exc}")

            # Check if file is already completed on disk
            if probe and probe.total_size and target_path.exists():
                disk_sz = target_path.stat().st_size
                if disk_sz == probe.total_size:
                    log.info(f"Skipping already-completed file: {target_path.name}")
                    item.status = QueueItemStatus.SKIPPED
                    item.is_skipped = True
                    item.downloaded_bytes = probe.total_size
                    item.total_bytes = probe.total_size
                    item.status_msg = "Skipped (Already Complete)"
                    item.completed_at = time.time()
                    self._notify_item_updated(item)
                    self._notify_item_completed(item)
                    self.save_state()
                    return

            # 3. Setup progress callback
            last_cb_time = 0.0
            def progress_cb(downloaded: int, total: Optional[int], speed: float, msg: str):
                nonlocal last_cb_time
                item.downloaded_bytes = downloaded
                if total:
                    item.total_bytes = total
                item.speed = speed
                item.status_msg = msg
                now = time.time()
                if now - last_cb_time >= 0.12:
                    last_cb_time = now
                    self._notify_item_updated(item)

            initial_bytes_on_disk = target_path.stat().st_size if target_path.exists() else 0

            # 4. Perform download via core engine
            res = download(
                url=item.url,
                headers=headers,
                dest_dir=str(out_dir),
                filename=item.filename,
                num_connections=self.num_connections,
                min_chunk_size=self.min_chunk_size,
                progress_callback=progress_cb,
                show_terminal_progress=False,
                cancel_event=item.cancel_event,
            )

            item.result = res
            item.downloaded_bytes = res.bytes_downloaded
            if res.total_size:
                item.total_bytes = res.total_size
            item.completed_at = time.time()

            # 5. Evaluate outcome
            if res.status == DownloadStatus.COMPLETED:
                # If file already existed and was complete (HTTP 416 or 0 new bytes)
                if initial_bytes_on_disk > 0 and res.bytes_downloaded == initial_bytes_on_disk and (probe and initial_bytes_on_disk == probe.total_size):
                    item.status = QueueItemStatus.SKIPPED
                    item.is_skipped = True
                    item.status_msg = "Skipped (Already Complete)"
                else:
                    item.status = QueueItemStatus.COMPLETED
                    item.status_msg = "Complete"
                item.speed = 0.0

            elif res.status == DownloadStatus.EXPIRED_URL:
                item.status = QueueItemStatus.EXPIRED
                item.status_msg = "Link Expired (403)"
                item.error = "Signed URL expired (HTTP 401/403/410)"
                item.speed = 0.0

            elif res.status == DownloadStatus.CANCELLED:
                item.status = QueueItemStatus.PAUSED
                item.status_msg = "Paused"
                item.speed = 0.0

            else:
                item.status = QueueItemStatus.FAILED
                item.status_msg = "Failed"
                item.error = res.error or "Download failed"
                item.speed = 0.0

            self._notify_item_updated(item)
            self._notify_item_completed(item)
            self.save_state()

        except Exception as exc:
            log.error(f"Unexpected worker failure for item {item.id}: {exc}", exc_info=True)
            item.status = QueueItemStatus.FAILED
            item.status_msg = "Error"
            item.error = str(exc)
            item.completed_at = time.time()
            self._notify_item_updated(item)
            self._notify_item_completed(item)
            self.save_state()

    # ── Notification Helpers ──────────────────────────────────────────

    def _notify_item_updated(self, item: QueueItem) -> None:
        if self.on_item_updated:
            try:
                self.on_item_updated(item)
            except Exception as exc:
                log.debug(f"Callback error on_item_updated: {exc}")

    def _notify_item_completed(self, item: QueueItem) -> None:
        if self.on_item_completed:
            try:
                self.on_item_completed(item)
            except Exception as exc:
                log.debug(f"Callback error on_item_completed: {exc}")

    # ── Summary Generation ────────────────────────────────────────────

    def get_summary(self) -> BatchSummary:
        """Aggregate current queue metrics into a BatchSummary."""
        with self._lock:
            items_copy = list(self.items)

        completed = sum(1 for it in items_copy if it.status == QueueItemStatus.COMPLETED)
        skipped = sum(1 for it in items_copy if it.status == QueueItemStatus.SKIPPED)
        expired = sum(1 for it in items_copy if it.status == QueueItemStatus.EXPIRED)
        failed = sum(1 for it in items_copy if it.status == QueueItemStatus.FAILED)
        cancelled = sum(
            1 for it in items_copy
            if it.status in (QueueItemStatus.CANCELLED, QueueItemStatus.PAUSED)
        )
        total_bytes = sum(it.downloaded_bytes for it in items_copy)
        duration = (time.time() - self._start_time) if self._start_time > 0 else 0.0

        return BatchSummary(
            total_items=len(items_copy),
            completed=completed,
            skipped=skipped,
            expired=expired,
            failed=failed,
            cancelled=cancelled,
            total_bytes_downloaded=total_bytes,
            duration=duration,
            items=items_copy,
        )
