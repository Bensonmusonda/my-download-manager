"""
Unfinished Recovery View for Smart Download Manager.
Scans disk for orphaned .part chunks and .meta.json manifests,
providing one-click URL updating and resumption.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List
import customtkinter as ctk

from state import find_unfinished_downloads
from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_DIM,
    COLOR_ACCENT,
    COLOR_WARNING,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    RADIUS_CARD,
    RADIUS_BUTTON,
    get_section_font,
    get_bold_font,
    get_body_font,
    get_caption_font,
)


def _format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


class RecoveryView(ctk.CTkFrame):
    """Disk Recovery View Container."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        get_dest_dir: Callable[[], str],
        on_resume_unfinished: Callable[[Path], None],
    ):
        super().__init__(parent, fg_color=COLOR_BG_WINDOW, corner_radius=0)
        self.get_dest_dir = get_dest_dir
        self.on_resume_unfinished = on_resume_unfinished

        self._build_ui()

    def _build_ui(self) -> None:
        # Header
        header = ctk.CTkFrame(self, height=42, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 6))
        header.pack_propagate(False)

        title_lbl = ctk.CTkLabel(
            header,
            text="Disk Recovery (Interrupted Downloads & Chunks)",
            font=get_section_font(),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        title_lbl.pack(side="left")

        refresh_btn = ctk.CTkButton(
            header,
            text=" Refresh Scan",
            image=get_icon("refresh", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=120,
            height=30,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.refresh_scan,
        )
        refresh_btn.pack(side="right")

        # Scrollable list
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def refresh_scan(self) -> None:
        for w in self.scroll_frame.winfo_children():
            w.destroy()

        dest = self.get_dest_dir()
        try:
            unfinished = find_unfinished_downloads(dest)
        except Exception:
            unfinished = []

        if not unfinished:
            empty_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            empty_frame.pack(fill="both", expand=True, pady=60)

            icon_lbl = ctk.CTkLabel(
                empty_frame,
                text="",
                image=get_icon("check", COLOR_TEXT_DIM, (36, 36)),
            )
            icon_lbl.pack(pady=(0, 10))

            lbl = ctk.CTkLabel(
                empty_frame,
                text="No incomplete downloads or orphaned chunks found in destination folder.",
                font=get_body_font(),
                text_color=COLOR_TEXT_MUTED,
            )
            lbl.pack()
            return

        for item in unfinished:
            card = ctk.CTkFrame(
                self.scroll_frame,
                fg_color=COLOR_BG_CARD,
                corner_radius=RADIUS_CARD,
                border_width=1,
                border_color=COLOR_BORDER,
                height=52,
            )
            card.pack(fill="x", padx=4, pady=3)
            card.pack_propagate(False)

            t_path = Path(item.target_file)
            size_txt = _format_bytes(item.downloaded_bytes)
            if item.total_bytes:
                size_txt += f" / {_format_bytes(item.total_bytes)}"

            # File icon
            ic_lbl = ctk.CTkLabel(
                card,
                text="",
                image=get_icon("file", COLOR_TEXT_MUTED, (16, 16)),
                width=24,
            )
            ic_lbl.pack(side="left", padx=(10, 6))

            name_lbl = ctk.CTkLabel(
                card,
                text=t_path.name,
                font=get_bold_font(),
                text_color=COLOR_TEXT_PRIMARY,
            )
            name_lbl.pack(side="left", padx=(0, 12))

            status_lbl = ctk.CTkLabel(
                card,
                text=f"({size_txt}) · {item.status}",
                font=get_caption_font(),
                text_color=COLOR_WARNING if "expired" in item.status.lower() else COLOR_TEXT_MUTED,
            )
            status_lbl.pack(side="left")

            resume_btn = ctk.CTkButton(
                card,
                text=" Update URL & Resume",
                image=get_icon("refresh", COLOR_TEXT_PRIMARY, (13, 13)),
                compound="left",
                font=get_caption_font(),
                width=160,
                height=28,
                corner_radius=RADIUS_BUTTON,
                fg_color=COLOR_ACCENT,
                command=lambda p=t_path: self.on_resume_unfinished(p),
            )
            resume_btn.pack(side="right", padx=10)
