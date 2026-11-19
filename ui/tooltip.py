"""
Modern Floating Tooltip Utility for CustomTkinter widgets.
Displays a subtle, dark floating pill with tooltip text on hover.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional
import customtkinter as ctk

from ui.theme import (
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    RADIUS_BUTTON,
    get_caption_font,
)


class Tooltip:
    """Floating tooltip for CTk widgets."""

    def __init__(self, widget: ctk.CTkBaseClass | tk.Widget, text: str, delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tooltip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, event=None) -> None:
        self._cancel_scheduled()
        self._after_id = self.widget.after(self.delay_ms, self._show_tooltip)

    def _on_leave(self, event=None) -> None:
        self._cancel_scheduled()
        self._hide_tooltip()

    def _cancel_scheduled(self) -> None:
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show_tooltip(self) -> None:
        if self.tooltip_window or not self.widget.winfo_exists():
            return

        x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6

        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)

        frame = ctk.CTkFrame(
            tw,
            fg_color="#090b0e",
            border_width=1,
            border_color="#333844",
            corner_radius=RADIUS_BUTTON,
        )
        frame.pack()

        label = ctk.CTkLabel(
            frame,
            text=self.text,
            font=get_caption_font(),
            text_color=COLOR_TEXT_PRIMARY,
            padx=8,
            pady=4,
        )
        label.pack()

        tw.update_idletasks()
        # Adjust so it's centered under widget
        w = tw.winfo_width()
        adj_x = max(10, x - (w // 2))
        tw.wm_geometry(f"+{adj_x}+{y}")

    def _hide_tooltip(self) -> None:
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
            self.tooltip_window = None
