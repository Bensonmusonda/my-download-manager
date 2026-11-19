"""
Batch Ingestion Modal Dialog for Smart Download Manager.
Allows importing urls.txt or pasting multiple URLs/magnets with instant preview.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, List
import customtkinter as ctk

from queue_manager import QueueItem, parse_urls_file
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
    get_bold_font,
    get_body_font,
    get_mono_font,
    get_caption_font,
)


class BatchIngestionModal(ctk.CTkToplevel):
    """Batch ingestion dialog with preview table."""

    def __init__(
        self,
        parent: ctk.CTk,
        default_dest: str,
        on_import: Callable[[List[QueueItem], bool], None],
    ):
        super().__init__(parent)
        self.parent = parent
        self.default_dest = default_dest
        self.on_import = on_import

        self.title("Batch Ingestion")
        self.geometry("680x520")
        self.minsize(600, 440)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)

        self.parsed_items: List[QueueItem] = []
        self._build_ui()

        self.bind("<Escape>", lambda e: self.destroy())
        self._center_window()

    def _center_window(self) -> None:
        self.update_idletasks()
        try:
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            px = self.parent.winfo_x()
            py = self.parent.winfo_y()
            w = 680
            h = 520
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # Header
        header = ctk.CTkFrame(container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        icon_lbl = ctk.CTkLabel(
            header,
            text="",
            image=get_icon("batch", COLOR_ACCENT, (22, 22)),
        )
        icon_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            header,
            text="Batch Ingestion (urls.txt)",
            font=get_title_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        title_lbl.pack(side="left")

        # Top action row: Browse file button & target folder
        top_bar = ctk.CTkFrame(container, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 10))

        file_btn = ctk.CTkButton(
            top_bar,
            text=" Select urls.txt File",
            image=get_icon("file", COLOR_TEXT_PRIMARY, (16, 16)),
            compound="left",
            height=34,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._on_choose_file,
        )
        file_btn.pack(side="left", padx=(0, 12))

        self.file_path_lbl = ctk.CTkLabel(
            top_bar,
            text="No file selected yet. Or paste URLs below:",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
        )
        self.file_path_lbl.pack(side="left")

        # Multiline Text Entry (for paste or file content)
        self.text_box = ctk.CTkTextbox(
            container,
            height=180,
            corner_radius=RADIUS_CARD,
            font=get_mono_font(),
            fg_color=COLOR_BG_CARD,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        self.text_box.pack(fill="both", expand=True, pady=(0, 10))
        self.text_box.insert(
            "1.0",
            "# Paste URLs below (one per line, format: URL | optional_filename | optional_referer)\n"
        )
        self.text_box.bind("<KeyRelease>", lambda e: self._update_preview_from_text())

        # Preview Summary Badge
        self.count_badge = ctk.CTkLabel(
            container,
            text="Parsed: 0 valid download tasks",
            font=get_bold_font(),
            text_color=COLOR_TEXT_MUTED,
        )
        self.count_badge.pack(anchor="w", pady=(0, 12))

        # Destination Folder Row
        dest_row = ctk.CTkFrame(container, fg_color="transparent")
        dest_row.pack(fill="x", pady=(0, 16))

        dest_lbl = ctk.CTkLabel(dest_row, text="Target Folder:", font=get_bold_font(), text_color=COLOR_TEXT_PRIMARY)
        dest_lbl.pack(side="left", padx=(0, 8))

        self.dest_entry = ctk.CTkEntry(
            dest_row,
            height=32,
            corner_radius=RADIUS_INPUT,
            font=get_body_font(),
        )
        self.dest_entry.insert(0, self.default_dest)
        self.dest_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        browse_dest_btn = ctk.CTkButton(
            dest_row,
            text=" Browse",
            image=get_icon("folder", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=90,
            height=32,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._on_browse_dest,
        )
        browse_dest_btn.pack(side="right")

        # Footer Actions
        footer = ctk.CTkFrame(container, fg_color="transparent")
        footer.pack(fill="x", side="bottom")

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

        self.import_start_btn = ctk.CTkButton(
            footer,
            text=" Import & Start Queue",
            image=get_icon("play", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=180,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            font=get_bold_font(),
            command=lambda: self._on_submit(auto_start=True),
        )
        self.import_start_btn.pack(side="right")

        self.import_paused_btn = ctk.CTkButton(
            footer,
            text=" Import Paused",
            image=get_icon("pause", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=130,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=lambda: self._on_submit(auto_start=False),
        )
        self.import_paused_btn.pack(side="right", padx=(0, 10))

    def _on_choose_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Select Batch File",
            filetypes=[("Text & Batch Files", "*.txt *.torrent"), ("All Files", "*.*")],
        )
        if not chosen:
            return

        self.file_path_lbl.configure(text=Path(chosen).name)
        try:
            with open(chosen, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self.text_box.delete("1.0", "end")
            self.text_box.insert("1.0", content)
            self._update_preview_from_text()
        except Exception as exc:
            messagebox.showerror("Read Error", f"Could not read file:\n{exc}")

    def _on_browse_dest(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.dest_entry.get().strip() or self.default_dest)
        if chosen:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, chosen)

    def _update_preview_from_text(self) -> None:
        lines = self.text_box.get("1.0", "end").splitlines()
        dest = self.dest_entry.get().strip() or self.default_dest
        valid_items: List[QueueItem] = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            parts = [p.strip().strip('"\'') for p in line.split("|")]
            url = parts[0]
            if url.startswith("http://") or url.startswith("https://") or url.startswith("magnet:") or url.endswith(".torrent"):
                fn = parts[1] if len(parts) >= 2 and parts[1] else None
                ref = parts[2] if len(parts) >= 3 and parts[2] else None
                valid_items.append(QueueItem(url=url, filename=fn, referer=ref, dest_dir=dest))

        self.parsed_items = valid_items
        count = len(valid_items)
        if count == 0:
            self.count_badge.configure(text="Parsed: 0 valid download tasks", text_color=COLOR_TEXT_MUTED)
        else:
            self.count_badge.configure(text=f"Parsed: {count} valid download tasks ready to import", text_color="#38bdf8")

    def _on_submit(self, auto_start: bool) -> None:
        self._update_preview_from_text()
        if not self.parsed_items:
            messagebox.showwarning("Empty Batch", "No valid URLs found to import.")
            return

        self.on_import(self.parsed_items, auto_start)
        self.destroy()
