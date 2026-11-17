"""
Smart Download Manager — gui.py

Modern desktop GUI built with CustomTkinter.
Features:
  • Clean dark-mode UI with native Windows controls
  • Live Chrome Extension Bridge (receives cf_clearance cookies & auto-catches downloads)
  • Anti-hotlink Referer tracking and auto-inference
  • Single-click download & batch file ingestion (urls.txt)
  • Background Download Queue Manager:
      - Sequential & concurrent task processing (e.g. 2 downloads active at once)
      - Individual progress bars, live transfer speed, and ETA per item
      - Start / Pause Queue controls & per-item Pause/Resume/Cancel
      - Auto-queueing of incoming downloads from Chrome Extension
      - Non-blocking HTTP 403 Expired URL handling with one-click refresh
  • Unfinished downloads scanner with one-click recovery and URL update
"""

from __future__ import annotations

import logging
import os
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, Optional
from urllib.parse import urlparse

import customtkinter as ctk

import browser_session
from bridge_server import BridgeServer, DEFAULT_BRIDGE_PORT
from browser_session import get_browser_session, make_session_headers
from downloader import (
    DEFAULT_NUM_CONNECTIONS,
    MULTI_CHUNK_MIN_SIZE,
    DownloadResult,
    DownloadStatus,
    download,
    filename_from_url,
    infer_referer,
)
from queue_manager import (
    BatchSummary,
    QueueItem,
    QueueItemStatus,
    QueueManager,
    parse_urls_file,
)
from state import DownloadManifest, find_unfinished_downloads

log = logging.getLogger(__name__)

# Appearance settings
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DEFAULT_DOWNLOAD_DIR = str(Path.cwd() / "downloads")


def _format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def _format_time(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds <= 0 or seconds > 86400 * 7:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class SmartDownloaderApp(ctk.CTk):
    """Main CustomTkinter desktop application window."""

    def __init__(
        self,
        default_dest: str = DEFAULT_DOWNLOAD_DIR,
        initial_batch_file: Optional[str] = None,
    ):
        super().__init__()

        self.title("Smart Download Manager")
        self.geometry("980x860")
        self.minsize(900, 750)

        self.dest_dir = default_dest
        self.active_expired_item_id: Optional[str] = None
        self.queue_item_widgets: Dict[str, dict] = {}

        # ── Initialize Background Queue Manager ─────────────────────────
        self.queue_mgr = QueueManager(
            dest_dir=self.dest_dir,
            max_concurrent=2,
            num_connections=DEFAULT_NUM_CONNECTIONS,
            min_chunk_size=MULTI_CHUNK_MIN_SIZE,
            on_item_updated=self._on_queue_item_updated_threadsafe,
            on_item_completed=self._on_queue_item_completed_threadsafe,
            on_queue_completed=self._on_queue_batch_completed_threadsafe,
        )

        self._build_ui()
        self._refresh_unfinished_list()

        # Start live Chrome Extension Bridge
        self.bridge = BridgeServer(
            port=DEFAULT_BRIDGE_PORT,
            on_download=self._on_extension_download,
            on_session=self._on_extension_session,
        )
        if self.bridge.start():
            self.bridge_badge.configure(
                text=f"🟢 Extension Bridge Active (Port {DEFAULT_BRIDGE_PORT})",
                text_color="#4ade80",
            )
        else:
            self.bridge_badge.configure(
                text="⚪ Extension Bridge Inactive",
                text_color="gray",
            )

        # Load initial batch file if specified via CLI
        if initial_batch_file:
            self.after(200, lambda: self._load_initial_batch_file(initial_batch_file))

        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _on_window_close(self) -> None:
        self.queue_mgr.stop()
        if self.bridge:
            self.bridge.stop()
        self.destroy()

    def _build_ui(self) -> None:
        """Construct the UI layout and cards."""
        # ── 1. Top Header ──────────────────────────────────────────────
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=24, pady=(14, 4))

        self.title_left = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.title_left.pack(side="left")

        self.title_label = ctk.CTkLabel(
            self.title_left,
            text="⬇ Smart Download Manager",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.title_label.pack(anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            self.title_left,
            text="Cloudflare-Ready · Multi-Connection Speed · Concurrent Queue & Batch",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self.subtitle_label.pack(anchor="w")

        # Top Right Extension Controls
        self.header_right = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_right.pack(side="right")

        self.bridge_badge = ctk.CTkLabel(
            self.header_right,
            text="Starting bridge...",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#4ade80",
        )
        self.bridge_badge.pack(anchor="e")

        self.ext_help_btn = ctk.CTkButton(
            self.header_right,
            text="📦 Setup Chrome Extension",
            width=160,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#2b719e",
            hover_color="#1f5475",
            command=self._show_extension_setup_dialog,
        )
        self.ext_help_btn.pack(anchor="e", pady=(4, 0))

        # ── 2. Download Input & Configuration Card ─────────────────────
        self.config_card = ctk.CTkFrame(self, corner_radius=12)
        self.config_card.pack(fill="x", padx=24, pady=6)

        # URL Input
        self.url_label = ctk.CTkLabel(
            self.config_card,
            text="Download URL / Magnet URI / .torrent File",
            font=ctk.CTkFont(weight="bold"),
        )
        self.url_label.grid(row=0, column=0, sticky="w", padx=16, pady=(8, 2))

        self.url_entry = ctk.CTkEntry(
            self.config_card,
            placeholder_text="Paste direct download URL, magnet:?xt=... URI, or local .torrent file path...",
            height=34,
        )
        self.url_entry.grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 6))
        self.url_entry.bind("<KeyRelease>", self._on_url_key_release)
        self.url_entry.bind("<Return>", lambda e: self._on_start_download())

        # Referer Input (Anti-Hotlink Header)
        self.referer_label = ctk.CTkLabel(
            self.config_card,
            text="Source Page / Referer (Auto-detected)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9ca3af",
        )
        self.referer_label.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 2))

        self.referer_entry = ctk.CTkEntry(
            self.config_card,
            placeholder_text="Source webpage URL (optional; prevents 403 hotlink protection block)",
            height=30,
        )
        self.referer_entry.grid(row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 6))

        # Destination Folder Input
        self.dest_label = ctk.CTkLabel(
            self.config_card,
            text="Save Folder",
            font=ctk.CTkFont(weight="bold"),
        )
        self.dest_label.grid(row=4, column=0, sticky="w", padx=16, pady=(0, 2))

        self.dest_entry = ctk.CTkEntry(self.config_card, height=32)
        self.dest_entry.insert(0, self.dest_dir)
        self.dest_entry.grid(row=5, column=0, columnspan=2, sticky="ew", padx=(16, 8), pady=(0, 8))

        self.browse_btn = ctk.CTkButton(
            self.config_card,
            text="Browse...",
            width=100,
            height=32,
            command=self._on_browse_dest,
        )
        self.browse_btn.grid(row=5, column=2, sticky="e", padx=(0, 16), pady=(0, 8))

        # Options & Controls Row
        self.options_frame = ctk.CTkFrame(self.config_card, fg_color="transparent")
        self.options_frame.grid(row=6, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 10))

        self.conn_label = ctk.CTkLabel(self.options_frame, text="Connections:")
        self.conn_label.pack(side="left", padx=(0, 6))

        self.conn_menu = ctk.CTkOptionMenu(
            self.options_frame,
            values=["1 (Single)", "2", "4", "6 (Recommended)", "8", "12"],
            width=135,
            command=self._on_connections_changed,
        )
        self.conn_menu.set("6 (Recommended)")
        self.conn_menu.pack(side="left", padx=(0, 14))

        self.chunk_label = ctk.CTkLabel(self.options_frame, text="Min Chunk:")
        self.chunk_label.pack(side="left", padx=(0, 6))

        self.chunk_menu = ctk.CTkOptionMenu(
            self.options_frame,
            values=["10 MB", "25 MB", "50 MB", "100 MB"],
            width=95,
            command=self._on_chunk_size_changed,
        )
        self.chunk_menu.set("50 MB")
        self.chunk_menu.pack(side="left", padx=(0, 16))

        # Action Buttons
        self.add_btn = ctk.CTkButton(
            self.options_frame,
            text="⬇ Add to Queue & Download",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#1f7a3a",
            hover_color="#18612e",
            height=34,
            width=180,
            command=self._on_start_download,
        )
        self.add_btn.pack(side="right")

        self.import_btn = ctk.CTkButton(
            self.options_frame,
            text="📥 Import urls.txt",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2b719e",
            hover_color="#1f5475",
            height=34,
            width=135,
            command=self._on_import_urls_file,
        )
        self.import_btn.pack(side="right", padx=(0, 8))

        self.torrent_btn = ctk.CTkButton(
            self.options_frame,
            text="📄 .torrent",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#4d4d4d",
            hover_color="#3d3d3d",
            height=34,
            width=95,
            command=self._on_choose_torrent_file,
        )
        self.torrent_btn.pack(side="right", padx=(0, 8))

        self.config_card.columnconfigure(0, weight=1)
        self.config_card.columnconfigure(1, weight=1)

        # ── 3. Expired Link Alert Card (Dynamic) ───────────────────────
        self.expired_card = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color="#362905",
            border_width=2,
            border_color="#d49b00",
        )

        self.expired_title = ctk.CTkLabel(
            self.expired_card,
            text="⚠️  Signed URL Expired (HTTP 401/403/410)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#ffcc00",
        )
        self.expired_title.pack(anchor="w", padx=16, pady=(8, 2))

        self.expired_desc = ctk.CTkLabel(
            self.expired_card,
            text="Your partial bytes are completely safe on disk! Paste a fresh URL (or click the Chrome extension icon on that tab) to resume remaining bytes:",
            text_color="#e6e6e6",
            wraplength=840,
            justify="left",
        )
        self.expired_desc.pack(anchor="w", padx=16, pady=(0, 6))

        self.fresh_url_entry = ctk.CTkEntry(
            self.expired_card,
            placeholder_text="Paste new/refreshed signed download URL here...",
            height=34,
        )
        self.fresh_url_entry.pack(fill="x", padx=16, pady=(0, 8))
        self.fresh_url_entry.bind("<Return>", lambda e: self._on_resume_refreshed_url())

        self.expired_btn_frame = ctk.CTkFrame(self.expired_card, fg_color="transparent")
        self.expired_btn_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.resume_btn = ctk.CTkButton(
            self.expired_btn_frame,
            text="🔄 Resume With Fresh URL",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#d49b00",
            hover_color="#b38300",
            text_color="#000000",
            command=self._on_resume_refreshed_url,
        )
        self.resume_btn.pack(side="left", padx=(0, 10))

        self.dismiss_btn = ctk.CTkButton(
            self.expired_btn_frame,
            text="Dismiss / Keep Paused",
            fg_color="#4d4d4d",
            hover_color="#3d3d3d",
            command=self._hide_expired_banner,
        )
        self.dismiss_btn.pack(side="left")

        # ── 4. Main Tabs: Download Queue & Unfinished Recovery ─────────
        self.tabview = ctk.CTkTabview(self, corner_radius=12)
        self.tabview.pack(fill="both", expand=True, padx=24, pady=(4, 12))

        self.queue_tab = self.tabview.add("📋 Download Queue")
        self.recovery_tab = self.tabview.add("📂 Unfinished Recovery on Disk")
        self.tabview.set("📋 Download Queue")

        # ── Tab 1: Download Queue Layout ──────────────────────────────
        self.queue_toolbar = ctk.CTkFrame(self.queue_tab, fg_color="transparent")
        self.queue_toolbar.pack(fill="x", padx=8, pady=(4, 8))

        self.queue_start_btn = ctk.CTkButton(
            self.queue_toolbar,
            text="▶ Start Queue",
            width=110,
            height=30,
            fg_color="#1f7a3a",
            hover_color="#18612e",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_toggle_queue_start,
        )
        self.queue_start_btn.pack(side="left", padx=(0, 8))

        self.queue_pause_btn = ctk.CTkButton(
            self.queue_toolbar,
            text="⏸ Pause Queue",
            width=110,
            height=30,
            fg_color="#a83232",
            hover_color="#852626",
            command=self._on_toggle_queue_pause,
        )
        self.queue_pause_btn.pack(side="left", padx=(0, 12))

        self.conc_label = ctk.CTkLabel(self.queue_toolbar, text="Concurrent:")
        self.conc_label.pack(side="left", padx=(0, 4))

        self.conc_menu = ctk.CTkOptionMenu(
            self.queue_toolbar,
            values=["1", "2", "3", "4", "6"],
            width=70,
            height=30,
            command=self._on_concurrency_changed,
        )
        self.conc_menu.set(str(self.queue_mgr.max_concurrent))
        self.conc_menu.pack(side="left", padx=(0, 16))

        self.clear_done_btn = ctk.CTkButton(
            self.queue_toolbar,
            text="🧹 Clear Done",
            width=100,
            height=30,
            fg_color="#3d3d3d",
            hover_color="#2b2b2b",
            command=self._on_clear_completed,
        )
        self.clear_done_btn.pack(side="left")

        self.queue_summary_badge = ctk.CTkLabel(
            self.queue_toolbar,
            text="Queue Empty",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray",
        )
        self.queue_summary_badge.pack(side="right", padx=8)

        # Scrollable container for queue item cards
        self.queue_scroll_list = ctk.CTkScrollableFrame(self.queue_tab)
        self.queue_scroll_list.pack(fill="both", expand=True, padx=4, pady=4)

        self.empty_queue_lbl = ctk.CTkLabel(
            self.queue_scroll_list,
            text="No items in download queue.\nPaste a URL above or click 'Import urls.txt' to load in bulk.",
            font=ctk.CTkFont(size=13),
            text_color="gray",
            justify="center",
        )
        self.empty_queue_lbl.pack(pady=40)

        # ── Tab 2: Unfinished Recovery Layout ─────────────────────────
        self.unf_header = ctk.CTkFrame(self.recovery_tab, fg_color="transparent")
        self.unf_header.pack(fill="x", padx=8, pady=(4, 8))

        self.unf_title = ctk.CTkLabel(
            self.unf_header,
            text="Interrupted files and partial chunks detected in destination folder:",
            font=ctk.CTkFont(size=13),
            text_color="gray",
        )
        self.unf_title.pack(side="left")

        self.scan_btn = ctk.CTkButton(
            self.unf_header,
            text="🔄 Refresh Scan",
            width=110,
            height=30,
            command=self._refresh_unfinished_list,
        )
        self.scan_btn.pack(side="right")

        self.unfinished_scroll_list = ctk.CTkScrollableFrame(self.recovery_tab)
        self.unfinished_scroll_list.pack(fill="both", expand=True, padx=4, pady=4)

    # -----------------------------------------------------------------------
    # Helper & Option Event Callbacks
    # -----------------------------------------------------------------------

    def _on_url_key_release(self, event=None) -> None:
        """Auto-populate Referer if user pastes a known CDN link."""
        url = self.url_entry.get().strip()
        if url:
            inferred = infer_referer(url)
            current_ref = self.referer_entry.get().strip()
            if inferred and not current_ref:
                self.referer_entry.delete(0, "end")
                self.referer_entry.insert(0, inferred)

    def _on_browse_dest(self) -> None:
        """Open folder dialog to pick destination."""
        chosen = filedialog.askdirectory(initialdir=self.dest_entry.get().strip() or DEFAULT_DOWNLOAD_DIR)
        if chosen:
            self.dest_dir = chosen
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, chosen)
            self.queue_mgr.dest_dir = chosen
            self._refresh_unfinished_list()

    def _get_connections_count(self) -> int:
        val = self.conn_menu.get().split()[0]
        try:
            return int(val)
        except ValueError:
            return DEFAULT_NUM_CONNECTIONS

    def _get_min_chunk_bytes(self) -> int:
        val = self.chunk_menu.get().split()[0]
        try:
            return int(val) * 1024 * 1024
        except ValueError:
            return MULTI_CHUNK_MIN_SIZE

    def _on_connections_changed(self, value: str) -> None:
        self.queue_mgr.num_connections = self._get_connections_count()

    def _on_chunk_size_changed(self, value: str) -> None:
        self.queue_mgr.min_chunk_size = self._get_min_chunk_bytes()

    def _on_concurrency_changed(self, value: str) -> None:
        try:
            self.queue_mgr.max_concurrent = int(value)
        except ValueError:
            self.queue_mgr.max_concurrent = 2

    # -----------------------------------------------------------------------
    # Extension Bridge Callbacks & Auto-Queueing
    # -----------------------------------------------------------------------

    def _on_extension_download(self, data: dict) -> None:
        """Called when Chrome extension sends a download task."""
        url = data.get("url", "")
        filename = data.get("filename", "")
        referer = data.get("referer", "")
        self.after(0, lambda: self._handle_incoming_extension_download(url, filename, referer))

    def _handle_incoming_extension_download(self, url: str, filename: str, referer: str = "") -> None:
        if not url:
            return
        dest = self.dest_entry.get().strip() or self.dest_dir
        ref = referer or infer_referer(url)

        # Enqueue task directly into background queue manager
        item = self.queue_mgr.add_item(url=url, filename=filename or None, referer=ref, dest_dir=dest)
        self.tabview.set("📋 Download Queue")

        # Auto-start queue if needed
        self.queue_mgr.start()
        self._update_queue_controls_state()

        self.bridge_badge.configure(
            text=f"⚡ Queued from Chrome: {item.display_name[:24]}",
            text_color="#4ade80",
        )

    def _on_extension_session(self, data: dict) -> None:
        """Called when Chrome extension sends updated session cookies."""
        domain = data.get("domain", "")
        referer = data.get("referer", "")
        has_cf = data.get("has_cf_clearance", False)
        self.after(0, lambda: self._handle_incoming_extension_session(domain, referer, has_cf))

    def _handle_incoming_extension_session(self, domain: str, referer: str, has_cf: bool) -> None:
        cf_badge = "✅ cf_clearance" if has_cf else "Session cookies"
        if referer and not self.referer_entry.get().strip():
            self.referer_entry.delete(0, "end")
            self.referer_entry.insert(0, referer)

        self.bridge_badge.configure(
            text=f"Received live {cf_badge} for {domain}!",
            text_color="#4ade80",
        )

        # If an item is currently paused on expired link for this domain, prompt resume
        if self.active_expired_item_id:
            item = self.queue_mgr.get_item(self.active_expired_item_id)
            if item and item.status == QueueItemStatus.EXPIRED:
                item_domain = urlparse(item.url).netloc
                if domain in item_domain or not item_domain:
                    self.queue_mgr.resume_item(item.id)
                    self._hide_expired_banner()

    def _show_extension_setup_dialog(self) -> None:
        """Display step-by-step instructions for loading the extension in Chrome."""
        ext_folder = str(Path.cwd() / "extension")
        win = ctk.CTkToplevel(self)
        win.title("Install Chrome Extension")
        win.geometry("640x420")
        win.transient(self)

        lbl = ctk.CTkLabel(
            win,
            text="How to Install the Smart Downloader Chrome Extension",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        lbl.pack(padx=20, pady=(20, 10))

        steps_text = (
            "1. Open Google Chrome (or Edge / Brave) and navigate to:\n"
            "   chrome://extensions/\n\n"
            "2. Turn on Developer mode (top right toggle).\n\n"
            "3. Click 'Load unpacked' (top left button).\n\n"
            "4. Select the extension directory:\n"
            f"   {ext_folder}\n\n"
            "5. That's it! The extension will now automatically bypass Cloudflare\n"
            "   by sharing cf_clearance sessions and catching downloads seamlessly."
        )
        txt = ctk.CTkLabel(win, text=steps_text, justify="left", font=ctk.CTkFont(size=12))
        txt.pack(padx=20, pady=10)

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(pady=16)

        open_folder_btn = ctk.CTkButton(
            btn_frame,
            text="📁 Open Extension Folder in Explorer",
            command=lambda: os.startfile(ext_folder),
        )
        open_folder_btn.pack(side="left", padx=8)

        close_btn = ctk.CTkButton(
            btn_frame,
            text="Close",
            fg_color="#4d4d4d",
            command=win.destroy,
        )
        close_btn.pack(side="left", padx=8)

    # -----------------------------------------------------------------------
    # Queue Controls & UI Updates
    # -----------------------------------------------------------------------

    def _on_start_download(self) -> None:
        """Add URL or magnet/torrent from top entry card to queue and start."""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a valid download URL, magnet URI, or .torrent file.")
            return

        dest = self.dest_entry.get().strip() or self.dest_dir
        referer = self.referer_entry.get().strip() or (infer_referer(url) if not url.startswith("magnet:") else None)

        self.queue_mgr.add_item(url=url, referer=referer, dest_dir=dest)
        self.url_entry.delete(0, "end")
        self.tabview.set("📋 Download Queue")

        self.queue_mgr.start()
        self._update_queue_controls_state()

    def _on_choose_torrent_file(self) -> None:
        """File dialog to pick a .torrent file and populate the input."""
        chosen = filedialog.askopenfilename(
            title="Select BitTorrent (.torrent) File",
            filetypes=[("Torrent Files", "*.torrent"), ("All Files", "*.*")],
        )
        if chosen:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, chosen)
            self.tabview.set("📋 Download Queue")

    def _on_import_urls_file(self) -> None:
        """File dialog to import urls.txt into the queue."""
        chosen = filedialog.askopenfilename(
            title="Import URLs / Torrents Batch File",
            filetypes=[("Text Files", "*.txt"), ("Torrent Files", "*.torrent"), ("All Files", "*.*")],
        )
        if not chosen:
            return

        dest = self.dest_entry.get().strip() or self.dest_dir
        try:
            if chosen.lower().endswith(".torrent"):
                item = self.queue_mgr.add_item(url=chosen, dest_dir=dest)
                messagebox.showinfo(
                    "Torrent Ingestion",
                    f"Successfully ingested torrent task:\n{Path(chosen).name}",
                )
            else:
                new_items = self.queue_mgr.add_items_from_file(chosen, dest_dir=dest)
                if not new_items:
                    messagebox.showinfo("Import Batch", "No valid URLs found in the selected file.")
                    return

                messagebox.showinfo(
                    "Batch Ingestion",
                    f"Successfully ingested {len(new_items)} download tasks from:\n{Path(chosen).name}",
                )
            self.tabview.set("📋 Download Queue")
            self.queue_mgr.start()
            self._update_queue_controls_state()
        except Exception as exc:
            messagebox.showerror("Import Error", f"Failed to parse file:\n{exc}")

    def _load_initial_batch_file(self, file_path: str) -> None:
        """Load batch file passed via CLI argument."""
        try:
            dest = self.dest_entry.get().strip() or self.dest_dir
            new_items = self.queue_mgr.add_items_from_file(file_path, dest_dir=dest)
            self.tabview.set("📋 Download Queue")
            self.queue_mgr.start()
            self._update_queue_controls_state()
        except Exception as exc:
            log.warning(f"Could not load initial batch file {file_path}: {exc}")

    def _on_toggle_queue_start(self) -> None:
        self.queue_mgr.start()
        self._update_queue_controls_state()

    def _on_toggle_queue_pause(self) -> None:
        self.queue_mgr.pause()
        self._update_queue_controls_state()

    def _on_clear_completed(self) -> None:
        self.queue_mgr.clear_completed()
        # Clean up UI widgets for removed items
        current_ids = {it.id for it in self.queue_mgr.items}
        for item_id in list(self.queue_item_widgets.keys()):
            if item_id not in current_ids:
                widgets = self.queue_item_widgets.pop(item_id)
                try:
                    widgets["frame"].destroy()
                except Exception:
                    pass
        self._update_queue_summary_badge()
        if not self.queue_mgr.items:
            self.empty_queue_lbl.pack(pady=40)

    def _update_queue_controls_state(self) -> None:
        if self.queue_mgr.is_running:
            self.queue_start_btn.configure(state="disabled", fg_color="#3d3d3d")
            self.queue_pause_btn.configure(state="normal", fg_color="#a83232")
        else:
            self.queue_start_btn.configure(state="normal", fg_color="#1f7a3a")
            self.queue_pause_btn.configure(state="disabled", fg_color="#3d3d3d")

    # -----------------------------------------------------------------------
    # Thread-Safe Queue Item UI Updates
    # -----------------------------------------------------------------------

    def _on_queue_item_updated_threadsafe(self, item: QueueItem) -> None:
        self.after(0, lambda: self._render_queue_item(item))

    def _on_queue_item_completed_threadsafe(self, item: QueueItem) -> None:
        self.after(0, lambda: self._handle_queue_item_finished(item))

    def _on_queue_batch_completed_threadsafe(self, summary: BatchSummary) -> None:
        self.after(0, lambda: self._handle_queue_batch_finished(summary))

    def _render_queue_item(self, item: QueueItem) -> None:
        """Create or update a card for a QueueItem in the scroll list."""
        if self.empty_queue_lbl.winfo_ismapped():
            self.empty_queue_lbl.pack_forget()

        if item.id not in self.queue_item_widgets:
            card = ctk.CTkFrame(self.queue_scroll_list, corner_radius=8)
            card.pack(fill="x", padx=4, pady=4)

            # Header row: Name + Status badge
            row1 = ctk.CTkFrame(card, fg_color="transparent")
            row1.pack(fill="x", padx=12, pady=(8, 2))

            name_lbl = ctk.CTkLabel(
                row1,
                text=item.display_name,
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            name_lbl.pack(side="left")

            stat_badge = ctk.CTkLabel(
                row1,
                text="Queued",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray",
            )
            stat_badge.pack(side="right")

            # Progress bar
            pbar = ctk.CTkProgressBar(card, height=10)
            pbar.set(0.0)
            pbar.pack(fill="x", padx=12, pady=4)

            # Details row: Stats + Action buttons
            row2 = ctk.CTkFrame(card, fg_color="transparent")
            row2.pack(fill="x", padx=12, pady=(2, 8))

            stats_lbl = ctk.CTkLabel(
                row2,
                text="Waiting in queue...",
                font=ctk.CTkFont(size=11),
                text_color="#9ca3af",
            )
            stats_lbl.pack(side="left")

            remove_btn = ctk.CTkButton(
                row2,
                text="✕",
                width=28,
                height=22,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#4d4d4d",
                hover_color="#3d3d3d",
                command=lambda: self._on_remove_queue_item(item.id),
            )
            remove_btn.pack(side="right", padx=(6, 0))

            action_btn = ctk.CTkButton(
                row2,
                text="Pause",
                width=80,
                height=22,
                font=ctk.CTkFont(size=11),
                fg_color="#3d3d3d",
                command=lambda: self._on_item_action_clicked(item.id),
            )
            action_btn.pack(side="right")

            self.queue_item_widgets[item.id] = {
                "frame": card,
                "name_lbl": name_lbl,
                "stat_badge": stat_badge,
                "pbar": pbar,
                "stats_lbl": stats_lbl,
                "action_btn": action_btn,
                "remove_btn": remove_btn,
            }

        w = self.queue_item_widgets[item.id]
        w["name_lbl"].configure(text=item.display_name)
        w["pbar"].set(item.progress_fraction)

        # Status text & badge color
        if item.status == QueueItemStatus.ACTIVE:
            if item.is_torrent_task:
                if item.peers > 0 or item.seeds > 0:
                    badge_text = f"⚡ Downloading ({item.formatted_speed} · {item.peers} peers · {item.seeds} seeds)"
                    stats_text = (
                        f"{item.formatted_size} ({item.progress_fraction * 100:.1f}%) · "
                        f"{item.formatted_speed} · {item.peers} peers · {item.seeds} seeds"
                    )
                else:
                    badge_text = f"⚡ {item.status_msg}"
                    stats_text = f"{item.formatted_size} ({item.progress_fraction * 100:.1f}%) · {item.status_msg}"
                w["stat_badge"].configure(text=badge_text, text_color="#3498db")
                w["stats_lbl"].configure(text=stats_text)
            else:
                spd_text = f" ({item.formatted_speed})" if item.speed > 0 else ""
                w["stat_badge"].configure(text=f"Downloading{spd_text}", text_color="#3498db")
                w["stats_lbl"].configure(
                    text=f"{item.formatted_size} ({item.progress_fraction * 100:.1f}%) · {item.formatted_speed}"
                )
            w["action_btn"].configure(text="Pause", fg_color="#a83232", state="normal")

        elif item.status == QueueItemStatus.QUEUED:
            w["stat_badge"].configure(text="Queued", text_color="gray")
            w["stats_lbl"].configure(text="Waiting for available download slot...")
            w["action_btn"].configure(text="Pause", fg_color="#4d4d4d", state="normal")

        elif item.status == QueueItemStatus.COMPLETED:
            if item.is_torrent_task:
                w["stat_badge"].configure(text="Complete ✅ (Torrent)", text_color="#2ecc71")
                w["stats_lbl"].configure(text=f"{item.formatted_size} · BitTorrent download finished")
            else:
                w["stat_badge"].configure(text="Complete ✅", text_color="#2ecc71")
                w["stats_lbl"].configure(text=f"{item.formatted_size} · Download finished")
            w["pbar"].set(1.0)
            w["action_btn"].configure(text="Open", fg_color="#1f7a3a", state="normal")

        elif item.status == QueueItemStatus.SKIPPED:
            w["stat_badge"].configure(text="Skipped (Already Complete) ⏩", text_color="#00bcd4")
            w["stats_lbl"].configure(text=f"{item.formatted_size} · Pre-existing file matched")
            w["pbar"].set(1.0)
            w["action_btn"].configure(text="Open", fg_color="#2b719e", state="normal")

        elif item.status == QueueItemStatus.EXPIRED:
            w["stat_badge"].configure(text="Link Expired (403) ⚠️", text_color="#ffcc00")
            w["stats_lbl"].configure(
                text=f"{item.formatted_size} saved · Needs fresh link to resume"
            )
            w["action_btn"].configure(
                text="🔄 Refresh",
                fg_color="#d49b00",
                text_color="#000000",
                state="normal",
            )

        elif item.status == QueueItemStatus.PAUSED:
            w["stat_badge"].configure(text="Paused ⏸", text_color="#f39c12")
            w["stats_lbl"].configure(text=f"{item.formatted_size} · Paused by user")
            w["action_btn"].configure(text="Resume", fg_color="#1f7a3a", state="normal")

        elif item.status == QueueItemStatus.FAILED:
            w["stat_badge"].configure(text="Failed ❌", text_color="#e74c3c")
            w["stats_lbl"].configure(text=item.error or "Download failed")
            w["action_btn"].configure(text="Retry", fg_color="#2b719e", state="normal")

        self._update_queue_summary_badge()

    def _handle_queue_item_finished(self, item: QueueItem) -> None:
        self._render_queue_item(item)
        self._refresh_unfinished_list()

        # If item expired, display the Expired Link Alert Card
        if item.status == QueueItemStatus.EXPIRED:
            self.active_expired_item_id = item.id
            self._show_expired_banner(item.display_name)

    def _handle_queue_batch_finished(self, summary: BatchSummary) -> None:
        self._update_queue_controls_state()
        self._update_queue_summary_badge()

        msg = (
            f"Batch Processing Completed!\n\n"
            f"• Total Tasks: {summary.total_items}\n"
            f"• Completed: {summary.completed}\n"
            f"• Skipped (Pre-existing): {summary.skipped}\n"
            f"• Expired Links (403): {summary.expired}\n"
            f"• Failed: {summary.failed}\n"
            f"• Total Downloaded: {_format_bytes(summary.total_bytes_downloaded)}\n"
            f"• Duration: {summary.duration:.1f}s"
        )
        if summary.expired > 0:
            msg += "\n\nTip: You can refresh expired downloads using the 'Refresh' button on each item."

        messagebox.showinfo("Batch Summary", msg)

    def _update_queue_summary_badge(self) -> None:
        active = sum(1 for it in self.queue_mgr.items if it.status == QueueItemStatus.ACTIVE)
        queued = sum(1 for it in self.queue_mgr.items if it.status == QueueItemStatus.QUEUED)
        expired = sum(1 for it in self.queue_mgr.items if it.status == QueueItemStatus.EXPIRED)
        done = sum(
            1 for it in self.queue_mgr.items
            if it.status in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED)
        )

        if not self.queue_mgr.items:
            self.queue_summary_badge.configure(text="Queue Empty", text_color="gray")
        else:
            self.queue_summary_badge.configure(
                text=f"{active} Active · {queued} Queued · {expired} Expired · {done} Done",
                text_color="#4ade80" if active > 0 else "gray",
            )

    def _on_item_action_clicked(self, item_id: str) -> None:
        """Handle per-item button click based on item state."""
        item = self.queue_mgr.get_item(item_id)
        if not item:
            return

        if item.status == QueueItemStatus.ACTIVE:
            self.queue_mgr.pause_item(item_id)
        elif item.status in (QueueItemStatus.PAUSED, QueueItemStatus.FAILED):
            self.queue_mgr.resume_item(item_id)
            self.queue_mgr.start()
            self._update_queue_controls_state()
        elif item.status == QueueItemStatus.EXPIRED:
            self.active_expired_item_id = item.id
            self._show_expired_banner(item.display_name)
        elif item.status in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED):
            if item.target_path and item.target_path.exists():
                try:
                    os.startfile(str(item.target_path.parent))
                except Exception:
                    pass

    def _on_remove_queue_item(self, item_id: str) -> None:
        self.queue_mgr.remove_item(item_id)
        if item_id in self.queue_item_widgets:
            w = self.queue_item_widgets.pop(item_id)
            try:
                w["frame"].destroy()
            except Exception:
                pass
        self._update_queue_summary_badge()
        if not self.queue_mgr.items:
            self.empty_queue_lbl.pack(pady=40)

    # -----------------------------------------------------------------------
    # Expired URL Handling & Link Refresh
    # -----------------------------------------------------------------------

    def _show_expired_banner(self, target_name: str) -> None:
        """Display the alert card prompting for a fresh link."""
        self.expired_title.configure(text=f"⚠️  Link Expired for '{target_name}' (HTTP 401/403/410)")
        self.expired_card.pack(fill="x", padx=24, pady=6, before=self.tabview)
        self.fresh_url_entry.delete(0, "end")
        self.fresh_url_entry.focus_set()

    def _hide_expired_banner(self) -> None:
        self.expired_card.pack_forget()
        self.active_expired_item_id = None

    def _on_resume_refreshed_url(self) -> None:
        fresh_url = self.fresh_url_entry.get().strip()
        if not fresh_url:
            return

        if self.active_expired_item_id:
            # Resume specific queue item
            self.queue_mgr.resume_item(self.active_expired_item_id, fresh_url=fresh_url)
            self.queue_mgr.start()
            self._update_queue_controls_state()
            self._hide_expired_banner()
        else:
            # Fallback: add fresh URL to queue directly
            dest = self.dest_entry.get().strip() or self.dest_dir
            self.queue_mgr.add_item(url=fresh_url, dest_dir=dest)
            self.queue_mgr.start()
            self._update_queue_controls_state()
            self._hide_expired_banner()

    # -----------------------------------------------------------------------
    # Unfinished Downloads Recovery Scanner
    # -----------------------------------------------------------------------

    def _refresh_unfinished_list(self) -> None:
        """Scan destination folder and populate the recovery scroll list."""
        for widget in self.unfinished_scroll_list.winfo_children():
            widget.destroy()

        dest = self.dest_entry.get().strip() or DEFAULT_DOWNLOAD_DIR
        unfinished = find_unfinished_downloads(dest)

        if not unfinished:
            empty_lbl = ctk.CTkLabel(
                self.unfinished_scroll_list,
                text="No incomplete downloads found in this folder.",
                text_color="gray",
            )
            empty_lbl.pack(pady=20)
            return

        for item in unfinished:
            item_frame = ctk.CTkFrame(self.unfinished_scroll_list, corner_radius=8)
            item_frame.pack(fill="x", padx=4, pady=4)

            t_name = Path(item.target_file).name
            size_txt = _format_bytes(item.downloaded_bytes)
            if item.total_bytes:
                size_txt += f" / {_format_bytes(item.total_bytes)}"

            name_lbl = ctk.CTkLabel(
                item_frame,
                text=t_name,
                font=ctk.CTkFont(weight="bold"),
            )
            name_lbl.pack(side="left", padx=12, pady=8)

            stat_lbl = ctk.CTkLabel(
                item_frame,
                text=f"({size_txt}) · {item.status}",
                text_color="#d49b00" if "expired" in item.status else "gray",
            )
            stat_lbl.pack(side="left", padx=8)

            resume_btn = ctk.CTkButton(
                item_frame,
                text="Update URL & Resume",
                width=150,
                height=28,
                fg_color="#2b719e",
                command=lambda p=Path(item.target_file): self._select_unfinished_for_update(p),
            )
            resume_btn.pack(side="right", padx=12, pady=6)

    def _select_unfinished_for_update(self, target_path: Path) -> None:
        """Prompt for a fresh URL to resume an unfinished download on disk."""
        self._show_expired_banner(target_path.name)


def run_gui(
    default_dest: str = DEFAULT_DOWNLOAD_DIR,
    initial_batch_file: Optional[str] = None,
) -> None:
    """Launch the CustomTkinter GUI mainloop."""
    app = SmartDownloaderApp(default_dest=default_dest, initial_batch_file=initial_batch_file)
    app.mainloop()


if __name__ == "__main__":
    run_gui()
