"""
Link Refresh Modal Dialog for Expired (HTTP 401/403/410) Downloads.
Provides item-specific link refresh without disrupting the main UI layout.
"""

from __future__ import annotations

from typing import Callable
import customtkinter as ctk

from queue_manager import QueueItem
from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    COLOR_WARNING_BG,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    RADIUS_CARD,
    RADIUS_BUTTON,
    RADIUS_INPUT,
    get_title_font,
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


class RefreshLinkModal(ctk.CTkToplevel):
    """Item-specific link refresh dialog."""

    def __init__(
        self,
        parent: ctk.CTk,
        item: QueueItem,
        on_refresh: Callable[[str, str, bool], None],
    ):
        super().__init__(parent)
        self.parent = parent
        self.item = item
        self.on_refresh = on_refresh

        self.title("Refresh Expired Download Link")
        self.geometry("580x360")
        self.minsize(520, 320)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)

        self._build_ui()
        self._inspect_clipboard()

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_submit())

        self._center_window()
        self.after(100, lambda: self.url_entry.focus_set())

    def _center_window(self) -> None:
        self.update_idletasks()
        try:
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            px = self.parent.winfo_x()
            py = self.parent.winfo_y()
            w = 580
            h = 360
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # Header with warning icon
        header = ctk.CTkFrame(container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        icon_lbl = ctk.CTkLabel(
            header,
            text="",
            image=get_icon("warning", COLOR_WARNING, (24, 24)),
        )
        icon_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            header,
            text="Signed Link Expired (HTTP 403 / 410)",
            font=get_title_font(),
            text_color=COLOR_WARNING,
        )
        title_lbl.pack(side="left")

        # Info card showing preserved bytes
        info_card = ctk.CTkFrame(
            container,
            fg_color=COLOR_WARNING_BG,
            corner_radius=RADIUS_CARD,
            border_width=1,
            border_color=COLOR_WARNING,
        )
        info_card.pack(fill="x", pady=(0, 14))

        filename_lbl = ctk.CTkLabel(
            info_card,
            text=self.item.display_name,
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        filename_lbl.pack(anchor="w", padx=14, pady=(10, 2))

        bytes_saved = _format_bytes(self.item.downloaded_bytes)
        status_sub = f"Partial download preserved: {bytes_saved} saved on disk. Remaining bytes will resume seamlessly."
        sub_lbl = ctk.CTkLabel(
            info_card,
            text=status_sub,
            font=get_caption_font(),
            text_color="#fef08a",  # Amber-100
        )
        sub_lbl.pack(anchor="w", padx=14, pady=(0, 10))

        # Fresh URL Input
        url_lbl = ctk.CTkLabel(
            container,
            text="Fresh Download URL",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        url_lbl.pack(anchor="w", pady=(0, 4))

        self.url_entry = ctk.CTkEntry(
            container,
            placeholder_text="Paste new or renewed download URL here...",
            height=36,
            corner_radius=RADIUS_INPUT,
            font=get_body_font(),
        )
        self.url_entry.pack(fill="x", pady=(0, 10))

        # Cookie re-harvest checkbox
        self.reharvest_var = ctk.BooleanVar(value=True)
        self.reharvest_check = ctk.CTkCheckBox(
            container,
            text="Re-harvest fresh browser cookies from Chrome extension",
            variable=self.reharvest_var,
            font=get_body_font(),
            text_color=COLOR_TEXT_MUTED,
            fg_color=COLOR_WARNING,
            hover_color="#d97706",
        )
        self.reharvest_check.pack(anchor="w", pady=(0, 16))

        # Footer Buttons
        footer = ctk.CTkFrame(container, fg_color="transparent")
        footer.pack(fill="x", side="bottom")

        cancel_btn = ctk.CTkButton(
            footer,
            text="Cancel / Keep Paused",
            width=130,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.destroy,
        )
        cancel_btn.pack(side="left")

        submit_btn = ctk.CTkButton(
            footer,
            text=" Resume Download Now",
            image=get_icon("refresh", "#000000", (16, 16)),
            compound="left",
            width=180,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_WARNING,
            hover_color="#d97706",
            text_color="#000000",
            font=get_bold_font(),
            command=self._on_submit,
        )
        submit_btn.pack(side="right")

    def _inspect_clipboard(self) -> None:
        try:
            cb_text = self.clipboard_get().strip()
            if cb_text and (cb_text.startswith("http://") or cb_text.startswith("https://")):
                if cb_text != self.item.url:
                    self.url_entry.delete(0, "end")
                    self.url_entry.insert(0, cb_text)
        except Exception:
            pass

    def _on_submit(self) -> None:
        fresh_url = self.url_entry.get().strip()
        if not fresh_url:
            self.url_entry.focus_set()
            return

        reharvest = self.reharvest_var.get()
        self.on_refresh(self.item.id, fresh_url, reharvest)
        self.destroy()
