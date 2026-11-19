"""
Chrome Extension Setup Guide Dialog for Smart Download Manager.
Walks the user through loading the unpacked Chrome / Edge MV3 extension.
"""

from __future__ import annotations

import os
from pathlib import Path
import customtkinter as ctk

from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_ACCENT,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    RADIUS_CARD,
    RADIUS_BUTTON,
    get_title_font,
    get_bold_font,
    get_body_font,
    get_mono_font,
)


class ExtensionSetupModal(ctk.CTkToplevel):
    """Step-by-step Chrome Extension setup dialog."""

    def __init__(self, parent: ctk.CTk):
        super().__init__(parent)
        self.parent = parent

        self.title("Chrome Extension Setup Guide")
        self.geometry("620x460")
        self.minsize(560, 420)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)

        self.ext_folder = str(Path.cwd() / "extension")
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
            w = 620
            h = 460
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
            image=get_icon("web", COLOR_ACCENT, (24, 24)),
        )
        icon_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            header,
            text="Install Smart Downloader Extension",
            font=get_title_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        title_lbl.pack(side="left")

        # Instruction Card
        card = ctk.CTkFrame(
            container,
            fg_color=COLOR_BG_CARD,
            corner_radius=RADIUS_CARD,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        card.pack(fill="both", expand=True, pady=(0, 16))

        steps = [
            "1. Open Chrome, Edge, or Brave and navigate to:",
            "   chrome://extensions/  (or edge://extensions/)",
            "",
            "2. Turn ON 'Developer mode' (toggle in top-right corner).",
            "",
            "3. Click the 'Load unpacked' button (top-left).",
            "",
            "4. Select the extension directory:",
            f"   {self.ext_folder}",
            "",
            "5. Done! The extension automatically catches downloads and",
            "   shares Cloudflare cf_clearance sessions on port 8992.",
        ]

        text_content = "\n".join(steps)
        info_lbl = ctk.CTkLabel(
            card,
            text=text_content,
            font=get_body_font(),
            text_color=COLOR_TEXT_PRIMARY,
            justify="left",
            anchor="w",
        )
        info_lbl.pack(fill="both", expand=True, padx=16, pady=16)

        # Footer Actions
        footer = ctk.CTkFrame(container, fg_color="transparent")
        footer.pack(fill="x", side="bottom")

        open_btn = ctk.CTkButton(
            footer,
            text=" Open Extension Folder in Explorer",
            image=get_icon("folder", COLOR_TEXT_PRIMARY, (16, 16)),
            compound="left",
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_ACCENT,
            command=self._on_open_folder,
        )
        open_btn.pack(side="left")

        close_btn = ctk.CTkButton(
            footer,
            text="Close",
            width=90,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.destroy,
        )
        close_btn.pack(side="right")

    def _on_open_folder(self) -> None:
        try:
            os.startfile(self.ext_folder)
        except Exception:
            pass
