"""
Preferences & Settings Modal Dialog for Smart Download Manager.
"""

from __future__ import annotations

from tkinter import filedialog
from typing import Callable, Dict
import customtkinter as ctk

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
    get_caption_font,
)


class SettingsModal(ctk.CTkToplevel):
    """Preferences & settings modal dialog."""

    def __init__(
        self,
        parent: ctk.CTk,
        current_settings: Dict,
        on_save: Callable[[Dict], None],
    ):
        super().__init__(parent)
        self.parent = parent
        self.settings = current_settings
        self.on_save = on_save

        self.title("Preferences & Settings")
        self.geometry("540x440")
        self.minsize(500, 380)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)

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
            w = 540
            h = 440
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
        header.pack(fill="x", pady=(0, 16))

        icon_lbl = ctk.CTkLabel(
            header,
            text="",
            image=get_icon("settings", COLOR_ACCENT, (22, 22)),
        )
        icon_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            header,
            text="Application Preferences",
            font=get_title_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        title_lbl.pack(side="left")

        # 1. Default Download Directory
        dest_lbl = ctk.CTkLabel(container, text="Default Download Folder", font=get_bold_font(), text_color=COLOR_TEXT_PRIMARY)
        dest_lbl.pack(anchor="w", pady=(0, 4))

        dest_row = ctk.CTkFrame(container, fg_color="transparent")
        dest_row.pack(fill="x", pady=(0, 14))

        self.dest_entry = ctk.CTkEntry(dest_row, height=34, corner_radius=RADIUS_INPUT, font=get_body_font())
        self.dest_entry.insert(0, self.settings.get("dest_dir", ""))
        self.dest_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        browse_btn = ctk.CTkButton(
            dest_row,
            text=" Browse",
            image=get_icon("folder", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=90,
            height=34,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._on_browse,
        )
        browse_btn.pack(side="right")

        # 2. Concurrency Limit
        grid_row = ctk.CTkFrame(container, fg_color="transparent")
        grid_row.pack(fill="x", pady=(0, 14))

        # Concurrency
        conc_box = ctk.CTkFrame(grid_row, fg_color="transparent")
        conc_box.pack(side="left", fill="x", expand=True, padx=(0, 8))

        conc_lbl = ctk.CTkLabel(conc_box, text="Max Concurrent Active Tasks", font=get_caption_font(), text_color=COLOR_TEXT_MUTED)
        conc_lbl.pack(anchor="w")

        self.conc_menu = ctk.CTkOptionMenu(
            conc_box,
            values=["1", "2", "3", "4", "6"],
            height=30,
            corner_radius=RADIUS_INPUT,
            fg_color=COLOR_BTN_SECONDARY,
        )
        self.conc_menu.set(str(self.settings.get("max_concurrent", 2)))
        self.conc_menu.pack(fill="x", pady=(2, 0))

        # Parallel Connections
        conn_box = ctk.CTkFrame(grid_row, fg_color="transparent")
        conn_box.pack(side="right", fill="x", expand=True, padx=(8, 0))

        conn_lbl = ctk.CTkLabel(conn_box, text="Default Parallel Connections", font=get_caption_font(), text_color=COLOR_TEXT_MUTED)
        conn_lbl.pack(anchor="w")

        self.conn_menu = ctk.CTkOptionMenu(
            conn_box,
            values=["1 (Single)", "2", "4", "6 (Recommended)", "8", "12"],
            height=30,
            corner_radius=RADIUS_INPUT,
            fg_color=COLOR_BTN_SECONDARY,
        )
        self.conn_menu.set(str(self.settings.get("num_connections", "6 (Recommended)")))
        self.conn_menu.pack(fill="x", pady=(2, 0))

        # 3. System Tray Behavior
        self.tray_var = ctk.BooleanVar(value=self.settings.get("minimize_to_tray", True))
        self.tray_check = ctk.CTkCheckBox(
            container,
            text="Minimize to Windows System Tray when closing window",
            variable=self.tray_var,
            font=get_body_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self.tray_check.pack(anchor="w", pady=(8, 14))

        # Footer
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

        save_btn = ctk.CTkButton(
            footer,
            text=" Save Preferences",
            image=get_icon("check", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=150,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            font=get_bold_font(),
            command=self._on_save,
        )
        save_btn.pack(side="right")

    def _on_browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.dest_entry.get().strip())
        if chosen:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, chosen)

    def _on_save(self) -> None:
        c_val = int(self.conc_menu.get())
        conn_str = self.conn_menu.get()
        try:
            conn_int = int(conn_str.split()[0])
        except Exception:
            conn_int = 6

        new_settings = {
            "dest_dir": self.dest_entry.get().strip(),
            "max_concurrent": c_val,
            "num_connections": conn_int,
            "minimize_to_tray": self.tray_var.get(),
        }
        self.on_save(new_settings)
        self.destroy()
