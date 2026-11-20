"""
Preferences & Settings Modal Dialog for Smart Download Manager.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable, Dict
import customtkinter as ctk

from storage_manager import SMART_FOLDER_NAME, get_default_download_dir
from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_DIM,
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
        self.geometry("560x540")
        self.minsize(520, 480)
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
            w = 560
            h = 540
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
        dest_row.pack(fill="x", pady=(0, 10))

        initial_dest = self.settings.get("dest_dir", "") or str(get_default_download_dir())
        self.dest_entry = ctk.CTkEntry(dest_row, height=34, corner_radius=RADIUS_INPUT, font=get_body_font())
        self.dest_entry.insert(0, initial_dest)
        self.dest_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.dest_entry.bind("<KeyRelease>", lambda e: self._update_preview())

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

        # 2. Smart Downloader Directory (Categorization by File Type)
        smart_frame = ctk.CTkFrame(
            container,
            fg_color=COLOR_BG_CARD,
            corner_radius=RADIUS_CARD,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        smart_frame.pack(fill="x", pady=(0, 14), padx=0)

        smart_inner = ctk.CTkFrame(smart_frame, fg_color="transparent")
        smart_inner.pack(fill="x", padx=12, pady=10)

        self.smart_var = ctk.BooleanVar(value=self.settings.get("use_smart_folders", True))
        self.smart_check = ctk.CTkCheckBox(
            smart_inner,
            text="Organize into Smart Downloader directory (by file type)",
            variable=self.smart_var,
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
            command=self._on_smart_toggle,
        )
        self.smart_check.pack(anchor="w")

        self.smart_desc = ctk.CTkLabel(
            smart_inner,
            text="Automatically sorts files into category folders:\n• Images, Videos, Documents, Audio, Archives, Programs, Torrents",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
        )
        self.smart_desc.pack(anchor="w", padx=24, pady=(2, 6))

        # Subfolder configuration row
        self.subfolder_row = ctk.CTkFrame(smart_inner, fg_color="transparent")
        self.subfolder_row.pack(fill="x", padx=24, pady=(2, 2))

        sub_lbl = ctk.CTkLabel(
            self.subfolder_row,
            text="Directory Name:",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
        )
        sub_lbl.pack(side="left", padx=(0, 8))

        self.smart_name_entry = ctk.CTkEntry(
            self.subfolder_row,
            height=28,
            width=180,
            corner_radius=RADIUS_INPUT,
            font=get_caption_font(),
        )
        self.smart_name_entry.insert(0, self.settings.get("smart_folder_name", SMART_FOLDER_NAME))
        self.smart_name_entry.pack(side="left")
        self.smart_name_entry.bind("<KeyRelease>", lambda e: self._update_preview())

        self.preview_lbl = ctk.CTkLabel(
            smart_inner,
            text="",
            font=get_caption_font(),
            text_color=COLOR_ACCENT,
            justify="left",
        )
        self.preview_lbl.pack(anchor="w", padx=24, pady=(4, 0))

        self._update_preview()

        # 3. Concurrency Limit & Parallel Connections
        grid_row = ctk.CTkFrame(container, fg_color="transparent")
        grid_row.pack(fill="x", pady=(0, 10))

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

        # 4. System Tray Behavior
        self.tray_var = ctk.BooleanVar(value=self.settings.get("minimize_to_tray", True))
        self.tray_check = ctk.CTkCheckBox(
            container,
            text="Minimize to Windows System Tray when closing window",
            variable=self.tray_var,
            font=get_body_font(),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self.tray_check.pack(anchor="w", pady=(4, 14))

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

    def _on_smart_toggle(self) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        dest = self.dest_entry.get().strip() or str(get_default_download_dir())
        subname = self.smart_name_entry.get().strip() or SMART_FOLDER_NAME
        if self.smart_var.get():
            self.preview_lbl.configure(
                text=f"📂 Preview: {dest}\\{subname}\\<Category> (e.g. \\Images)",
                text_color="#38bdf8",
            )
            self.smart_name_entry.configure(state="normal")
        else:
            self.preview_lbl.configure(
                text=f"📂 Downloads will save directly into: {dest}",
                text_color=COLOR_TEXT_MUTED,
            )
            self.smart_name_entry.configure(state="disabled")

    def _on_browse(self) -> None:
        init_dir = self.dest_entry.get().strip() or str(get_default_download_dir())
        chosen = filedialog.askdirectory(initialdir=init_dir)
        if chosen:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, chosen)
            self._update_preview()

    def _on_save(self) -> None:
        c_val = int(self.conc_menu.get())
        conn_str = self.conn_menu.get()
        try:
            conn_int = int(conn_str.split()[0])
        except Exception:
            conn_int = 6

        dest = self.dest_entry.get().strip() or str(get_default_download_dir())
        smart_name = self.smart_name_entry.get().strip() or SMART_FOLDER_NAME

        new_settings = {
            "dest_dir": dest,
            "use_smart_folders": self.smart_var.get(),
            "smart_folder_name": smart_name,
            "max_concurrent": c_val,
            "num_connections": conn_int,
            "minimize_to_tray": self.tray_var.get(),
        }
        self.on_save(new_settings)
        self.destroy()
