"""
Main Application Window Shell for Smart Download Manager.
Implements the Modern Sidebar + Top Toolbar + High-Density Queue View + Status Bar layout.
Strictly adheres to Phase 6 UI/UX specification in HANDOFF.md.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional
import customtkinter as ctk

from bridge_server import BridgeServer, DEFAULT_BRIDGE_PORT
from browser_session import get_browser_session, make_session_headers
from downloader import (
    DEFAULT_NUM_CONNECTIONS,
    MULTI_CHUNK_MIN_SIZE,
    infer_referer,
)
from queue_manager import (
    BatchSummary,
    QueueItem,
    QueueItemStatus,
    QueueManager,
)
from ui.icons import get_icon
from ui.modals.add_modal import AddDownloadModal
from ui.modals.batch_modal import BatchIngestionModal
from ui.modals.ext_setup_modal import ExtensionSetupModal
from ui.modals.refresh_modal import RefreshLinkModal
from ui.modals.settings_modal import SettingsModal
from ui.queue_view import QueueView
from ui.recovery_view import RecoveryView
from ui.sidebar import NavigationSidebar
from storage_manager import (
    get_default_download_dir,
    load_settings,
    save_settings,
    resolve_download_folder,
    get_file_category,
    SMART_FOLDER_NAME,
)
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_DIM,
    COLOR_ACCENT,
    COLOR_SUCCESS,
    COLOR_WARNING,
    MIN_WIDTH,
    MIN_HEIGHT,
    WINDOW_WIDTH,
    WINDOW_HEIGHT,
    get_caption_font,
    get_mono_font,
)
from ui.toolbar import TopToolbar
from ui.tray import WindowsSystemTray

log = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_DIR = str(get_default_download_dir())


def _format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


class SmartDownloaderApp(ctk.CTk):
    """Main CustomTkinter modern desktop application window."""

    def __init__(
        self,
        default_dest: str = DEFAULT_DOWNLOAD_DIR,
        initial_batch_file: Optional[str] = None,
    ):
        super().__init__()

        self.title("Smart Download Manager")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.configure(fg_color=COLOR_BG_WINDOW)

        # ── Load Persisted Application Preferences ───────────────────────
        self.app_settings = load_settings()
        persisted_dest = self.app_settings.get("dest_dir", DEFAULT_DOWNLOAD_DIR)
        if default_dest and default_dest != DEFAULT_DOWNLOAD_DIR:
            self.dest_dir = default_dest
        else:
            self.dest_dir = persisted_dest or DEFAULT_DOWNLOAD_DIR

        self.use_smart_folders: bool = self.app_settings.get("use_smart_folders", True)
        self.smart_folder_name: str = self.app_settings.get("smart_folder_name", SMART_FOLDER_NAME)
        self.minimize_to_tray_pref: bool = self.app_settings.get("minimize_to_tray", True)
        self.remember_tray_pref: bool = False
        self.current_view_name = "queue"  # "queue" or "recovery"

        # ── Initialize Background Queue Manager ─────────────────────────
        self.queue_mgr = QueueManager(
            dest_dir=self.dest_dir,
            max_concurrent=self.app_settings.get("max_concurrent", 2),
            num_connections=self.app_settings.get("num_connections", DEFAULT_NUM_CONNECTIONS),
            min_chunk_size=MULTI_CHUNK_MIN_SIZE,
            on_item_updated=self._on_queue_item_updated_threadsafe,
            on_item_completed=self._on_queue_item_completed_threadsafe,
            on_queue_completed=self._on_queue_batch_completed_threadsafe,
        )

        # ── Build Shell Layout ──────────────────────────────────────────
        self._build_shell()
        self._bind_keyboard_shortcuts()

        # ── Initialize System Tray ──────────────────────────────────────
        self.tray = WindowsSystemTray(
            icon_path=str(Path.cwd() / "app_icon.ico"),
            tooltip="Smart Download Manager",
            on_restore=self._restore_from_tray,
            on_pause_all=self._on_pause_all,
            on_resume_all=self._on_resume_all,
            on_exit=self._exit_completely,
            get_bridge_status=self._get_bridge_status_text,
        )
        self.tray.start()

        # ── Start Chrome Extension Bridge ───────────────────────────────
        self.bridge = BridgeServer(
            port=DEFAULT_BRIDGE_PORT,
            on_download=self._on_extension_download,
            on_session=self._on_extension_session,
        )
        self.bridge_active = self.bridge.start()
        self._update_bridge_status_indicator()

        # ── Start Telemetry Periodic Loop ───────────────────────────────
        self._schedule_telemetry_tick()

        # Load initial batch file if specified via CLI
        if initial_batch_file:
            self.after(200, lambda: self._load_initial_batch_file(initial_batch_file))

        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self._center_window()

    def _center_window(self) -> None:
        self.update_idletasks()
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - WINDOW_WIDTH) // 2)
            y = max(0, (sh - WINDOW_HEIGHT) // 2)
            self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Shell Architecture Layout
    # -----------------------------------------------------------------------

    def _build_shell(self) -> None:
        # 1. Navigation Sidebar (Left, 200px)
        self.sidebar = NavigationSidebar(
            self,
            on_filter_changed=self._on_sidebar_filter_changed,
            on_open_recovery=self._show_recovery_view,
            on_open_settings=self._open_settings_dialog,
        )
        self.sidebar.pack(side="left", fill="y")

        # 2. Main Right Work Area
        self.work_area = ctk.CTkFrame(self, fg_color=COLOR_BG_WINDOW, corner_radius=0)
        self.work_area.pack(side="right", fill="both", expand=True)

        # 2a. Top Toolbar (54px)
        self.toolbar = TopToolbar(
            self.work_area,
            on_add_download=self._open_add_download_modal,
            on_add_torrent=self._open_torrent_browser,
            on_batch_ingest=self._open_batch_ingestion_modal,
            on_resume_all=self._on_resume_all,
            on_pause_all=self._on_pause_all,
            on_clear_completed=self._on_clear_completed,
            on_search_query=self._on_search_query_changed,
            on_concurrency_changed=self._on_concurrency_changed,
            initial_concurrency=self.queue_mgr.max_concurrent,
        )
        self.toolbar.pack(fill="x")

        # 2b. Bottom Status Bar (26px)
        self.status_bar = ctk.CTkFrame(
            self.work_area,
            height=26,
            corner_radius=0,
            fg_color=COLOR_BG_CARD,
            border_width=0,
        )
        self.status_bar.pack(side="bottom", fill="x")
        self.status_bar.pack_propagate(False)
        self._build_status_bar()

        # 2c. Center Workspace Viewports
        self.viewport_container = ctk.CTkFrame(self.work_area, fg_color="transparent", corner_radius=0)
        self.viewport_container.pack(fill="both", expand=True)

        # Queue View
        self.queue_view = QueueView(
            self.viewport_container,
            on_add_click=self._open_add_download_modal,
            on_pause_item=self.queue_mgr.pause_item,
            on_resume_item=lambda i_id: (self.queue_mgr.resume_item(i_id), self.queue_mgr.start()),
            on_refresh_item=self._open_refresh_modal,
            on_remove_item=self._on_remove_queue_item,
            on_delete_disk=self._on_delete_item_from_disk,
        )
        self.queue_view.pack(fill="both", expand=True)

        # Recovery View (Hidden by default)
        self.recovery_view = RecoveryView(
            self.viewport_container,
            get_dest_dir=lambda: self.dest_dir,
            on_resume_unfinished=self._on_resume_unfinished_from_disk,
        )

    def _build_status_bar(self) -> None:
        inner = ctk.CTkFrame(self.status_bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12)

        # Left: Bridge Indicator
        self.bridge_indicator_btn = ctk.CTkButton(
            inner,
            text=" Extension Bridge: Inactive",
            image=get_icon("dot", COLOR_TEXT_DIM, (10, 10)),
            compound="left",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
            fg_color="transparent",
            hover_color="#334155",
            height=22,
            command=self._open_extension_setup_dialog,
        )
        self.bridge_indicator_btn.pack(side="left")

        # Right: Disk Free Space Telemetry
        self.storage_lbl = ctk.CTkLabel(
            inner,
            text="",
            font=get_mono_font(),
            text_color=COLOR_TEXT_MUTED,
        )
        self.storage_lbl.pack(side="right")

        # Center: Speed and Active Tasks Metrics
        self.speed_metrics_lbl = ctk.CTkLabel(
            inner,
            text="0 Active Tasks · 0 B/s",
            font=get_mono_font(),
            text_color=COLOR_TEXT_MUTED,
        )
        self.speed_metrics_lbl.pack(side="left", padx=24)

    def _update_bridge_status_indicator(self) -> None:
        if self.bridge_active:
            self.bridge_indicator_btn.configure(
                text=f" Bridge: Active (Port {DEFAULT_BRIDGE_PORT})",
                image=get_icon("dot", COLOR_SUCCESS, (10, 10)),
                text_color=COLOR_SUCCESS,
            )
        else:
            self.bridge_indicator_btn.configure(
                text=" Bridge: Inactive",
                image=get_icon("dot", COLOR_TEXT_DIM, (10, 10)),
                text_color=COLOR_TEXT_DIM,
            )

    def _get_bridge_status_text(self) -> str:
        if self.bridge_active:
            return f"Extension Bridge: Active (Port {DEFAULT_BRIDGE_PORT})"
        return "Extension Bridge: Inactive"

    # -----------------------------------------------------------------------
    # Keyboard Shortcuts & Navigation
    # -----------------------------------------------------------------------

    def _bind_keyboard_shortcuts(self) -> None:
        self.bind("<Control-n>", lambda e: self._open_add_download_modal())
        self.bind("<Control-N>", lambda e: self._open_add_download_modal())
        self.bind("<Control-o>", lambda e: self._open_save_folder())
        self.bind("<Control-O>", lambda e: self._open_save_folder())
        self.bind("<Control-f>", lambda e: self.toolbar.focus_search())
        self.bind("<Control-F>", lambda e: self.toolbar.focus_search())
        self.bind("<Control-a>", lambda e: self.queue_view.select_all())
        self.bind("<Control-A>", lambda e: self.queue_view.select_all())
        self.bind("<space>", lambda e: self._on_space_pressed())
        self.bind("<Delete>", lambda e: self._on_delete_pressed())
        self.bind("<Escape>", lambda e: self.queue_view.clear_selection())

    def _on_space_pressed(self) -> None:
        selected_ids = self.queue_view.get_selected_ids()
        if not selected_ids:
            return
        for item_id in selected_ids:
            item = self.queue_mgr.get_item(item_id)
            if not item:
                continue
            if item.status == QueueItemStatus.ACTIVE:
                self.queue_mgr.pause_item(item_id)
            elif item.status in (QueueItemStatus.PAUSED, QueueItemStatus.FAILED):
                self.queue_mgr.resume_item(item_id)
        self.queue_mgr.start()

    def _on_delete_pressed(self) -> None:
        selected_ids = self.queue_view.get_selected_ids()
        if not selected_ids:
            return
        for item_id in selected_ids:
            self._on_remove_queue_item(item_id)

    def _open_save_folder(self) -> None:
        dest = Path(self.dest_dir)
        smart_path = dest / self.smart_folder_name
        target = smart_path if (self.use_smart_folders and smart_path.exists()) else dest
        target.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(target))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(target)])
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # View Switching (Queue vs Recovery)
    # -----------------------------------------------------------------------

    def _on_sidebar_filter_changed(self, category: str) -> None:
        if self.current_view_name != "queue":
            self.recovery_view.pack_forget()
            self.queue_view.pack(fill="both", expand=True)
            self.current_view_name = "queue"
        self.queue_view.set_category_filter(category)

    def _show_recovery_view(self) -> None:
        if self.current_view_name != "recovery":
            self.queue_view.pack_forget()
            self.recovery_view.pack(fill="both", expand=True)
            self.current_view_name = "recovery"
            self.sidebar.set_active_filter("recovery")
        self.recovery_view.refresh_scan()

    def _on_search_query_changed(self, query: str) -> None:
        self.queue_view.set_search_query(query)

    # -----------------------------------------------------------------------
    # Modal Openers & Actions
    # -----------------------------------------------------------------------

    def _open_add_download_modal(self) -> None:
        AddDownloadModal(
            self,
            default_dest=self.dest_dir,
            on_add=self._handle_add_download,
            use_smart_folders=self.use_smart_folders,
            smart_folder_name=self.smart_folder_name,
        )

    def _handle_add_download(
        self,
        url: str,
        filename: Optional[str],
        referer: Optional[str],
        dest_dir: str,
        auto_start: bool,
        num_connections: int,
        min_chunk_size: int,
    ) -> Optional[QueueItem]:
        self.queue_mgr.num_connections = num_connections
        self.queue_mgr.min_chunk_size = min_chunk_size

        item = self.queue_mgr.add_item(url=url, filename=filename, referer=referer, dest_dir=dest_dir)
        if auto_start:
            self.queue_mgr.start()
        else:
            item.status = QueueItemStatus.PAUSED
            item.status_msg = "Paused"

        self._on_sidebar_filter_changed("all")
        self._refresh_all_ui()
        return item

    def _open_torrent_browser(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Select BitTorrent (.torrent) File",
            filetypes=[("Torrent Files", "*.torrent"), ("All Files", "*.*")],
        )
        if chosen:
            dest = resolve_download_folder(
                self.dest_dir,
                name_or_url=chosen,
                use_smart_folders=self.use_smart_folders,
                smart_folder_name=self.smart_folder_name,
            )
            self.queue_mgr.add_item(url=chosen, dest_dir=str(dest))
            self.queue_mgr.start()
            self._refresh_all_ui()

    def _open_batch_ingestion_modal(self) -> None:
        BatchIngestionModal(
            self,
            default_dest=self.dest_dir,
            on_import=self._handle_batch_import,
            use_smart_folders=self.use_smart_folders,
            smart_folder_name=self.smart_folder_name,
        )

    def _handle_batch_import(self, items: List[QueueItem], auto_start: bool) -> None:
        for it in items:
            self.queue_mgr.add_item(url=it.url, filename=it.filename, referer=it.referer, dest_dir=it.dest_dir)
            if not auto_start:
                it.status = QueueItemStatus.PAUSED
                it.status_msg = "Paused"

        if auto_start:
            self.queue_mgr.start()

        self._on_sidebar_filter_changed("all")
        self._refresh_all_ui()

    def _open_refresh_modal(self, item_id: str) -> None:
        item = self.queue_mgr.get_item(item_id)
        if not item:
            return
        RefreshLinkModal(
            self,
            item=item,
            on_refresh=self._handle_refresh_submit,
        )

    def _handle_refresh_submit(self, item_id: str, fresh_url: str, reharvest: bool) -> None:
        self.queue_mgr.resume_item(item_id, fresh_url=fresh_url)
        self.queue_mgr.start()
        self._refresh_all_ui()

    def _open_extension_setup_dialog(self) -> None:
        ExtensionSetupModal(self)

    def _open_settings_dialog(self) -> None:
        current_cfg = {
            "dest_dir": self.dest_dir,
            "use_smart_folders": self.use_smart_folders,
            "smart_folder_name": self.smart_folder_name,
            "max_concurrent": self.queue_mgr.max_concurrent,
            "num_connections": self.queue_mgr.num_connections,
            "minimize_to_tray": self.minimize_to_tray_pref,
        }
        SettingsModal(
            self,
            current_settings=current_cfg,
            on_save=self._handle_settings_save,
        )

    def _handle_settings_save(self, new_cfg: dict) -> None:
        self.dest_dir = new_cfg.get("dest_dir", self.dest_dir)
        self.use_smart_folders = new_cfg.get("use_smart_folders", self.use_smart_folders)
        self.smart_folder_name = new_cfg.get("smart_folder_name", self.smart_folder_name)
        self.queue_mgr.dest_dir = self.dest_dir
        self.queue_mgr.max_concurrent = new_cfg.get("max_concurrent", self.queue_mgr.max_concurrent)
        self.queue_mgr.num_connections = new_cfg.get("num_connections", self.queue_mgr.num_connections)
        self.minimize_to_tray_pref = new_cfg.get("minimize_to_tray", True)
        self.toolbar.conc_menu.set(str(self.queue_mgr.max_concurrent))

        # Persist to disk
        save_settings({
            "dest_dir": self.dest_dir,
            "use_smart_folders": self.use_smart_folders,
            "smart_folder_name": self.smart_folder_name,
            "max_concurrent": self.queue_mgr.max_concurrent,
            "num_connections": self.queue_mgr.num_connections,
            "minimize_to_tray": self.minimize_to_tray_pref,
        })

        self._refresh_all_ui()

    def _on_resume_unfinished_from_disk(self, target_path: Path) -> None:
        # Prompt for fresh URL to resume unfinished file
        temp_item = QueueItem(
            url="",
            filename=target_path.name,
            dest_dir=str(target_path.parent),
            target_path=target_path,
        )
        if target_path.exists():
            temp_item.downloaded_bytes = target_path.stat().st_size

        RefreshLinkModal(
            self,
            item=temp_item,
            on_refresh=lambda _, fresh_url, __: self._handle_add_download(
                url=fresh_url,
                filename=target_path.name,
                referer=infer_referer(fresh_url),
                dest_dir=str(target_path.parent),
                auto_start=True,
                num_connections=self.queue_mgr.num_connections,
                min_chunk_size=self.queue_mgr.min_chunk_size,
            ),
        )

    # -----------------------------------------------------------------------
    # Queue Controls
    # -----------------------------------------------------------------------

    def _on_resume_all(self) -> None:
        for it in self.queue_mgr.items:
            if it.status in (QueueItemStatus.PAUSED, QueueItemStatus.FAILED):
                self.queue_mgr.resume_item(it.id)
        self.queue_mgr.start()
        self._refresh_all_ui()

    def _on_pause_all(self) -> None:
        self.queue_mgr.pause()
        self._refresh_all_ui()

    def _on_clear_completed(self) -> None:
        self.queue_mgr.clear_completed()
        self._refresh_all_ui()

    def _on_concurrency_changed(self, limit: int) -> None:
        self.queue_mgr.max_concurrent = limit

    def _on_remove_queue_item(self, item_id: str) -> None:
        self.queue_mgr.remove_item(item_id)
        self._refresh_all_ui()

    def _on_delete_item_from_disk(self, item_id: str) -> None:
        item = self.queue_mgr.get_item(item_id)
        if not item:
            return
        ans = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete '{item.display_name}' and its partial/completed files from disk?",
            parent=self,
        )
        if ans:
            self.queue_mgr.remove_item(item_id)
            if item.target_path and item.target_path.exists():
                try:
                    os.remove(item.target_path)
                except Exception:
                    pass
            # Also clean up part or meta files
            part_file = Path(item.dest_dir) / f"{item.display_name}.part"
            meta_file = Path(item.dest_dir) / f"{item.display_name}.meta.json"
            if part_file.exists():
                try:
                    os.remove(part_file)
                except Exception:
                    pass
            if meta_file.exists():
                try:
                    os.remove(meta_file)
                except Exception:
                    pass
            self._refresh_all_ui()

    # -----------------------------------------------------------------------
    # Thread-Safe Queue Callbacks & Periodic Telemetry
    # -----------------------------------------------------------------------

    def _on_queue_item_updated_threadsafe(self, item: QueueItem) -> None:
        self.after(0, self._refresh_all_ui)

    def _on_queue_item_completed_threadsafe(self, item: QueueItem) -> None:
        self.after(0, self._refresh_all_ui)

    def _on_queue_batch_completed_threadsafe(self, summary: BatchSummary) -> None:
        self.after(0, lambda: self._handle_batch_summary(summary))

    def _handle_batch_summary(self, summary: BatchSummary) -> None:
        self._refresh_all_ui()
        if summary.total_items > 1:
            msg = (
                f"Batch Complete!\n\n"
                f"• Total: {summary.total_items}\n"
                f"• Completed: {summary.completed}\n"
                f"• Skipped: {summary.skipped}\n"
                f"• Expired (403): {summary.expired}\n"
                f"• Failed: {summary.failed}\n"
                f"• Total Downloaded: {_format_bytes(summary.total_bytes_downloaded)}"
            )
            messagebox.showinfo("Batch Summary", msg, parent=self)

    def _schedule_telemetry_tick(self) -> None:
        self._update_status_bar_telemetry()
        self.after(1000, self._schedule_telemetry_tick)

    def _refresh_all_ui(self) -> None:
        items = list(self.queue_mgr.items)
        self.queue_view.update_items(items)

        # Update sidebar counts
        total = len(items)
        downloading = sum(1 for it in items if it.status == QueueItemStatus.ACTIVE)
        paused = sum(1 for it in items if it.status in (QueueItemStatus.PAUSED, QueueItemStatus.QUEUED))
        expired = sum(1 for it in items if it.status == QueueItemStatus.EXPIRED)
        completed = sum(1 for it in items if it.status in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED))
        http_count = sum(1 for it in items if not it.is_torrent_task)
        torrent_count = sum(1 for it in items if it.is_torrent_task)

        self.sidebar.update_counts(
            total=total,
            downloading=downloading,
            paused=paused,
            expired=expired,
            completed=completed,
            http_count=http_count,
            torrent_count=torrent_count,
        )

        self._update_status_bar_telemetry()

    def _update_status_bar_telemetry(self) -> None:
        items = self.queue_mgr.items
        active_items = [it for it in items if it.status == QueueItemStatus.ACTIVE]
        active_count = len(active_items)
        total_dl_speed = sum(it.speed for it in active_items)

        # Speed telemetry
        if total_dl_speed > 0:
            dl_str = f"DL: {_format_bytes(int(total_dl_speed))}/s"
        else:
            dl_str = "0 B/s"

        self.speed_metrics_lbl.configure(text=f"{active_count} Active Tasks · {dl_str}")

        # Tray tooltip update
        if self.tray:
            tray_text = f"Smart Downloader: {active_count} active ({dl_str})" if active_count > 0 else "Smart Download Manager: Idle"
            self.tray.update_tooltip(tray_text)

        # Storage telemetry
        try:
            usage = shutil.disk_usage(self.dest_dir)
            free_str = _format_bytes(usage.free)
            dest_short = self.dest_dir if len(self.dest_dir) < 32 else f"...{self.dest_dir[-28:]}"
            self.storage_lbl.configure(text=f"Save Disk: {free_str} Free · {dest_short}")
        except Exception:
            self.storage_lbl.configure(text=f"Save Disk: {self.dest_dir}")

    # -----------------------------------------------------------------------
    # Chrome Extension Bridge Handlers
    # -----------------------------------------------------------------------

    def _on_extension_download(self, data: dict) -> None:
        url = data.get("url", "")
        filename = data.get("filename", "")
        referer = data.get("referer", "")
        self.after(0, lambda: self._handle_extension_download(url, filename, referer))

    def _handle_extension_download(self, url: str, filename: str, referer: str) -> None:
        if not url:
            return
        dest = str(
            resolve_download_folder(
                self.dest_dir,
                name_or_url=filename or url,
                use_smart_folders=self.use_smart_folders,
                smart_folder_name=self.smart_folder_name,
            )
        )
        ref = referer or infer_referer(url)
        self.queue_mgr.add_item(url=url, filename=filename or None, referer=ref, dest_dir=dest)
        self.queue_mgr.start()
        self._on_sidebar_filter_changed("all")
        self._refresh_all_ui()

    def _on_extension_session(self, data: dict) -> None:
        domain = data.get("domain", "")
        referer = data.get("referer", "")
        has_cf = data.get("has_cf_clearance", False)
        self.after(0, lambda: self._handle_extension_session(domain, referer, has_cf))

    def _handle_extension_session(self, domain: str, referer: str, has_cf: bool) -> None:
        # Check if any expired items can now be resumed
        for it in self.queue_mgr.items:
            if it.status == QueueItemStatus.EXPIRED:
                if domain in it.url:
                    self.queue_mgr.resume_item(it.id)
                    self.queue_mgr.start()
                    self._refresh_all_ui()

    def _load_initial_batch_file(self, file_path: str) -> None:
        try:
            self.queue_mgr.add_items_from_file(file_path, dest_dir=self.dest_dir)
            self.queue_mgr.start()
            self._refresh_all_ui()
        except Exception as exc:
            log.warning(f"Failed to load initial batch file: {exc}")

    # -----------------------------------------------------------------------
    # System Tray & Window Lifecycle
    # -----------------------------------------------------------------------

    def _restore_from_tray(self) -> None:
        self.after(0, self._do_restore)

    def _do_restore(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_window_close(self) -> None:
        active_count = sum(1 for it in self.queue_mgr.items if it.status == QueueItemStatus.ACTIVE)

        if active_count > 0 and self.minimize_to_tray_pref:
            if not self.remember_tray_pref:
                ans = messagebox.askyesnocancel(
                    "Smart Download Manager",
                    f"{active_count} download(s) are currently in progress.\n\n"
                    "Would you like to keep downloading in the background in the System Tray?\n\n"
                    "• Click [Yes] to minimize to System Tray\n"
                    "• Click [No] to exit completely",
                    parent=self,
                )
                if ans is None:
                    # Cancel close
                    return
                elif ans:
                    self.remember_tray_pref = True
                    self.withdraw()
                    return
                else:
                    self._exit_completely()
                    return
            else:
                self.withdraw()
                return

        self._exit_completely()

    def _exit_completely(self) -> None:
        self.queue_mgr.stop()
        if self.bridge:
            self.bridge.stop()
        if self.tray:
            self.tray.stop()
        self.destroy()
