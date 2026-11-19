"""
Smart 'New Download' Modal Dialog for Smart Download Manager.
Features clipboard auto-inspection, file name inference, folder picker,
and collapsible Advanced HTTP & Anti-Hotlink Options accordion.
"""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Optional
import customtkinter as ctk

from downloader import (
    DEFAULT_NUM_CONNECTIONS,
    MULTI_CHUNK_MIN_SIZE,
    filename_from_url,
    infer_referer,
)
from queue_manager import QueueItem
from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_ACCENT,
    COLOR_ACCENT_HOVER,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    RADIUS_CARD,
    RADIUS_BUTTON,
    RADIUS_INPUT,
    get_title_font,
    get_section_font,
    get_bold_font,
    get_body_font,
    get_caption_font,
)


class AddDownloadModal(ctk.CTkToplevel):
    """Smart New Download Modal Dialog."""

    def __init__(
        self,
        parent: ctk.CTk,
        default_dest: str,
        on_add: Callable[[str, Optional[str], Optional[str], str, bool, int, int], Optional[QueueItem]],
    ):
        super().__init__(parent)
        self.parent = parent
        self.default_dest = default_dest
        self.on_add = on_add

        self.title("New Download")
        self.geometry("620x540")
        self.minsize(560, 480)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)

        self.advanced_visible = False
        self._build_ui()
        self._inspect_clipboard()

        # Keyboard shortcuts
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_start_click())

        # Center on parent
        self._center_window()
        self.after(100, self._focus_appropriate_entry)

    def _center_window(self) -> None:
        self.update_idletasks()
        try:
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            px = self.parent.winfo_x()
            py = self.parent.winfo_y()
            w = 620
            h = 540
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # Header with icon
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 16))

        logo_lbl = ctk.CTkLabel(
            header_frame,
            text="",
            image=get_icon("plus", COLOR_ACCENT, (22, 22)),
        )
        logo_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            header_frame,
            text="Add New Download Task",
            font=get_title_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        title_lbl.pack(side="left")

        # 1. URL / Magnet Input
        url_label = ctk.CTkLabel(
            container,
            text="Download URL, Magnet URI, or .torrent Path",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        url_label.pack(anchor="w", pady=(0, 4))

        self.url_entry = ctk.CTkEntry(
            container,
            placeholder_text="https://... or magnet:?xt=... or path to .torrent",
            height=36,
            corner_radius=RADIUS_INPUT,
            font=get_body_font(),
        )
        self.url_entry.pack(fill="x", pady=(0, 12))
        self.url_entry.bind("<KeyRelease>", self._on_url_changed)

        # 2. File Name (Optional)
        name_label = ctk.CTkLabel(
            container,
            text="File Name (Optional - auto-inferred from URL)",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        name_label.pack(anchor="w", pady=(0, 4))

        self.name_entry = ctk.CTkEntry(
            container,
            placeholder_text="Leave blank to detect automatically",
            height=34,
            corner_radius=RADIUS_INPUT,
            font=get_body_font(),
        )
        self.name_entry.pack(fill="x", pady=(0, 12))

        # 3. Save Folder
        folder_label = ctk.CTkLabel(
            container,
            text="Save Folder",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        folder_label.pack(anchor="w", pady=(0, 4))

        folder_row = ctk.CTkFrame(container, fg_color="transparent")
        folder_row.pack(fill="x", pady=(0, 12))

        self.folder_entry = ctk.CTkEntry(
            folder_row,
            height=34,
            corner_radius=RADIUS_INPUT,
            font=get_body_font(),
        )
        self.folder_entry.insert(0, self.default_dest)
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        browse_btn = ctk.CTkButton(
            folder_row,
            text=" Browse",
            image=get_icon("folder", COLOR_TEXT_PRIMARY, (16, 16)),
            compound="left",
            width=100,
            height=34,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._on_browse_folder,
        )
        browse_btn.pack(side="right")

        # 4. Collapsible Advanced Options Accordion
        self.accordion_btn = ctk.CTkButton(
            container,
            text=" > Advanced HTTP & Anti-Hotlink Options",
            font=get_section_font(),
            text_color=COLOR_TEXT_MUTED,
            fg_color="transparent",
            hover_color=COLOR_BG_CARD,
            anchor="w",
            height=30,
            command=self._toggle_advanced,
        )
        self.accordion_btn.pack(fill="x", pady=(0, 6))

        self.advanced_frame = ctk.CTkFrame(
            container,
            fg_color=COLOR_BG_CARD,
            corner_radius=RADIUS_CARD,
            border_width=1,
            border_color=COLOR_BORDER,
        )

        # Advanced contents: Referer
        adv_ref_lbl = ctk.CTkLabel(
            self.advanced_frame,
            text="Referer / Anti-Hotlink URL",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        adv_ref_lbl.pack(anchor="w", padx=14, pady=(10, 2))

        self.referer_entry = ctk.CTkEntry(
            self.advanced_frame,
            placeholder_text="Source webpage URL (auto-inferred if empty)",
            height=30,
            corner_radius=RADIUS_INPUT,
            font=get_body_font(),
        )
        self.referer_entry.pack(fill="x", padx=14, pady=(0, 10))

        # Advanced contents: Concurrency & Chunking
        adv_grid = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        adv_grid.pack(fill="x", padx=14, pady=(0, 12))

        # Connections dropdown
        conn_box = ctk.CTkFrame(adv_grid, fg_color="transparent")
        conn_box.pack(side="left", fill="x", expand=True, padx=(0, 8))

        conn_lbl = ctk.CTkLabel(conn_box, text="Parallel Connections", font=get_caption_font(), text_color=COLOR_TEXT_MUTED)
        conn_lbl.pack(anchor="w")

        self.conn_menu = ctk.CTkOptionMenu(
            conn_box,
            values=["1 (Single)", "2", "4", "6 (Recommended)", "8", "12"],
            height=28,
            corner_radius=RADIUS_INPUT,
            fg_color=COLOR_BTN_SECONDARY,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
        )
        self.conn_menu.set("6 (Recommended)")
        self.conn_menu.pack(fill="x", pady=(2, 0))

        # Min chunk dropdown
        chunk_box = ctk.CTkFrame(adv_grid, fg_color="transparent")
        chunk_box.pack(side="right", fill="x", expand=True, padx=(8, 0))

        chunk_lbl = ctk.CTkLabel(chunk_box, text="Min Chunk Threshold", font=get_caption_font(), text_color=COLOR_TEXT_MUTED)
        chunk_lbl.pack(anchor="w")

        self.chunk_menu = ctk.CTkOptionMenu(
            chunk_box,
            values=["10 MB", "25 MB", "50 MB", "100 MB"],
            height=28,
            corner_radius=RADIUS_INPUT,
            fg_color=COLOR_BTN_SECONDARY,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
        )
        self.chunk_menu.set("50 MB")
        self.chunk_menu.pack(fill="x", pady=(2, 0))

        # 5. Footer Action Buttons
        footer = ctk.CTkFrame(container, fg_color="transparent")
        footer.pack(fill="x", side="bottom", pady=(14, 0))

        cancel_btn = ctk.CTkButton(
            footer,
            text="Cancel",
            width=90,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.destroy,
        )
        cancel_btn.pack(side="left")

        self.start_btn = ctk.CTkButton(
            footer,
            text=" Start Download",
            image=get_icon("play", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=150,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            font=get_bold_font(),
            command=self._on_start_click,
        )
        self.start_btn.pack(side="right")

        self.paused_btn = ctk.CTkButton(
            footer,
            text=" Add Paused",
            image=get_icon("pause", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=120,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._on_add_paused_click,
        )
        self.paused_btn.pack(side="right", padx=(0, 10))

    def _inspect_clipboard(self) -> None:
        """Auto-populate URL field if system clipboard contains a download link."""
        try:
            cb_text = self.clipboard_get().strip()
            if cb_text:
                if (
                    cb_text.startswith("http://")
                    or cb_text.startswith("https://")
                    or cb_text.startswith("magnet:?xt=")
                    or (cb_text.endswith(".torrent") and os.path.exists(cb_text))
                ):
                    self.url_entry.delete(0, "end")
                    self.url_entry.insert(0, cb_text)
                    self._on_url_changed()
        except Exception:
            pass

    def _focus_appropriate_entry(self) -> None:
        if self.url_entry.get().strip():
            self.start_btn.focus_set()
        else:
            self.url_entry.focus_set()

    def _on_url_changed(self, event=None) -> None:
        url = self.url_entry.get().strip()
        if not url:
            return

        # Auto-infer referer
        if not self.referer_entry.get().strip():
            inferred_ref = infer_referer(url)
            if inferred_ref:
                self.referer_entry.delete(0, "end")
                self.referer_entry.insert(0, inferred_ref)

        # Auto-infer filename preview
        if not self.name_entry.get().strip():
            try:
                fn = filename_from_url(url)
                if fn and not fn.startswith("download"):
                    self.name_entry.delete(0, "end")
                    self.name_entry.insert(0, fn)
            except Exception:
                pass

    def _toggle_advanced(self) -> None:
        if self.advanced_visible:
            self.advanced_frame.pack_forget()
            self.accordion_btn.configure(text=" > Advanced HTTP & Anti-Hotlink Options")
            self.advanced_visible = False
        else:
            self.advanced_frame.pack(fill="x", pady=(0, 8), before=self.accordion_btn.master.winfo_children()[-1])
            self.accordion_btn.configure(text=" v Advanced HTTP & Anti-Hotlink Options")
            self.advanced_visible = True

    def _on_browse_folder(self) -> None:
        init_dir = self.folder_entry.get().strip() or self.default_dest
        chosen = filedialog.askdirectory(initialdir=init_dir)
        if chosen:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, chosen)

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

    def _on_start_click(self) -> None:
        self._submit(auto_start=True)

    def _on_add_paused_click(self) -> None:
        self._submit(auto_start=False)

    def _submit(self, auto_start: bool) -> None:
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a valid download URL, magnet URI, or .torrent file.")
            self.url_entry.focus_set()
            return

        filename = self.name_entry.get().strip() or None
        dest_dir = self.folder_entry.get().strip() or self.default_dest
        referer = self.referer_entry.get().strip() or (infer_referer(url) if not url.startswith("magnet:") else None)
        num_conn = self._get_connections_count()
        chunk_size = self._get_min_chunk_bytes()

        self.on_add(url, filename, referer, dest_dir, auto_start, num_conn, chunk_size)
        self.destroy()
