"""
Preferences & Settings Modal — Sprint 7 Tabbed Overhaul.

Implements a professional left-sidebar navigation + right-panel content layout
matching the architecture described in HANDOFF.md § 3.1.

Tabs:
  ⚙  General        – startup, close action, completion behavior
  📁 Downloads      – folder, smart categorization, custom categories, conflict policy
  ⚡ Connection     – concurrency, chunks, speed limits
  🧲 BitTorrent     – port, seeding, DHT/PeX, encryption
  🌐 Network        – proxy, bridge, retries
  🔄 Updates        – GitHub self-updater, channel, manual check
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Dict, List, Optional
import customtkinter as ctk

from storage_manager import (
    SMART_FOLDER_NAME,
    get_default_download_dir,
    get_run_on_startup,
    set_run_on_startup,
)
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
    COLOR_SUCCESS,
    COLOR_WARNING,
    RADIUS_CARD,
    RADIUS_BUTTON,
    RADIUS_INPUT,
    get_title_font,
    get_bold_font,
    get_body_font,
    get_caption_font,
)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
_SIDEBAR_W = 160
_PANEL_PAD_X = 24
_PANEL_PAD_Y = 18
_SECTION_GAP = 14
_ROW_H = 32
_WINDOW_W = 820
_WINDOW_H = 600

_NAV_ITEMS = [
    ("⚙", "General"),
    ("📁", "Downloads"),
    ("⚡", "Connection"),
    ("🧲", "BitTorrent"),
    ("🌐", "Network"),
    ("🔄", "Updates"),
]

# Conflict policy options label → stored value
_CONFLICT_OPTS: Dict[str, str] = {
    "Auto-rename (append (1), (2)…)": "rename",
    "Prompt user for action": "prompt",
    "Skip duplicate download": "skip",
    "Overwrite existing file": "overwrite",
}
_CONFLICT_LABELS = list(_CONFLICT_OPTS.keys())
_CONFLICT_VALUES = list(_CONFLICT_OPTS.values())

# Close action options
_CLOSE_OPTS: Dict[str, str] = {
    "Minimize to System Tray": "tray",
    "Exit Application Completely": "exit",
    "Ask me every time": "ask",
}
_CLOSE_LABELS = list(_CLOSE_OPTS.keys())
_CLOSE_VALUES = list(_CLOSE_OPTS.values())

# On-complete action
_COMPLETE_OPTS: Dict[str, str] = {
    "Do nothing": "nothing",
    "Show system notification": "notify",
    "Open containing folder": "open_folder",
    "Open downloaded file": "open_file",
    "Play completion chime": "chime",
}
_COMPLETE_LABELS = list(_COMPLETE_OPTS.keys())
_COMPLETE_VALUES = list(_COMPLETE_OPTS.values())

# Encryption options
_ENC_OPTS: Dict[str, str] = {
    "Enabled (prefer encrypted)": "enabled",
    "Required (force encrypted)": "required",
    "Disabled": "disabled",
}
_ENC_LABELS = list(_ENC_OPTS.keys())
_ENC_VALUES = list(_ENC_OPTS.values())


def _rval(labels, values, stored):
    """Return the label for the stored value, defaulting to first label."""
    try:
        return labels[values.index(stored)]
    except (ValueError, IndexError):
        return labels[0]


# ---------------------------------------------------------------------------
# Custom Category Editor dialog
# ---------------------------------------------------------------------------

class _CategoryEditorDialog(ctk.CTkToplevel):
    """Small inline dialog to add or edit a custom download category."""

    def __init__(
        self,
        parent,
        existing_name: str = "",
        existing_exts: str = "",
        on_save: Optional[Callable[[str, str], None]] = None,
    ):
        super().__init__(parent)
        self.on_save_cb = on_save
        self.title("Custom Category")
        self.geometry("360x200")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)
        self.grab_set()

        pad = ctk.CTkFrame(self, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(pad, text="Category Name:", font=get_bold_font(), text_color=COLOR_TEXT_PRIMARY).pack(anchor="w")
        self._name = ctk.CTkEntry(pad, height=32, corner_radius=RADIUS_INPUT, font=get_body_font())
        self._name.insert(0, existing_name)
        self._name.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(pad, text="File Extensions (comma-separated):", font=get_bold_font(), text_color=COLOR_TEXT_PRIMARY).pack(anchor="w")
        self._exts = ctk.CTkEntry(pad, height=32, corner_radius=RADIUS_INPUT, font=get_body_font(),
                                  placeholder_text="e.g. stl, obj, fbx, blend")
        self._exts.insert(0, existing_exts)
        self._exts.pack(fill="x", pady=(4, 14))

        btn_row = ctk.CTkFrame(pad, fg_color="transparent")
        btn_row.pack(fill="x")
        ctk.CTkButton(btn_row, text="Cancel", width=80, height=30, corner_radius=RADIUS_BUTTON,
                      fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER,
                      command=self.destroy).pack(side="left")
        ctk.CTkButton(btn_row, text="Save", width=80, height=30, corner_radius=RADIUS_BUTTON,
                      fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
                      command=self._do_save).pack(side="right")

        self._name.focus()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._do_save())

    def _do_save(self):
        name = self._name.get().strip()
        exts = self._exts.get().strip()
        if not name or not exts:
            messagebox.showwarning("Incomplete", "Please fill in both fields.", parent=self)
            return
        if self.on_save_cb:
            self.on_save_cb(name, exts)
        self.destroy()


# ---------------------------------------------------------------------------
# Main Preferences Modal
# ---------------------------------------------------------------------------

class SettingsModal(ctk.CTkToplevel):
    """
    Sprint 7 Tabbed Preferences & Settings Center.
    Left sidebar navigation — right content panels (one per tab, swapped in/out).
    """

    def __init__(
        self,
        parent: ctk.CTk,
        current_settings: Dict,
        on_save: Callable[[Dict], None],
    ):
        super().__init__(parent)
        self.parent = parent
        self.settings = dict(current_settings)  # working copy
        self.on_save = on_save

        self.title("Preferences & Settings")
        self.geometry(f"{_WINDOW_W}x{_WINDOW_H}")
        self.minsize(680, 520)
        self.resizable(True, True)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)

        self._active_tab: str = "General"
        self._panels: Dict[str, ctk.CTkFrame] = {}
        self._nav_buttons: Dict[str, ctk.CTkButton] = {}

        # Custom categories: local mutable list of (name, [exts]) tuples
        raw_cc = self.settings.get("custom_categories", {})
        self._custom_cats: List[tuple[str, List[str]]] = [
            (k, list(v)) for k, v in raw_cc.items()
        ]

        self._build_ui()
        self.bind("<Escape>", lambda e: self.destroy())
        self._center_window()

    # -----------------------------------------------------------------------
    # Window Helpers
    # -----------------------------------------------------------------------

    def _center_window(self) -> None:
        self.update_idletasks()
        try:
            pw, ph = self.parent.winfo_width(), self.parent.winfo_height()
            px, py = self.parent.winfo_x(), self.parent.winfo_y()
            x = px + max(0, (pw - _WINDOW_W) // 2)
            y = py + max(0, (ph - _WINDOW_H) // 2)
            self.geometry(f"{_WINDOW_W}x{_WINDOW_H}+{x}+{y}")
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Shell Layout
    # -----------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Outer container ─────────────────────────────────────────────
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True)

        # ── Left sidebar ─────────────────────────────────────────────────
        sidebar = ctk.CTkFrame(
            outer,
            width=_SIDEBAR_W,
            fg_color=COLOR_BG_CARD,
            corner_radius=0,
        )
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # App name / logo strip
        hdr = ctk.CTkFrame(sidebar, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(16, 12))
        ctk.CTkLabel(
            hdr,
            text="Preferences",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        ).pack(anchor="w")

        sep = ctk.CTkFrame(sidebar, height=1, fg_color=COLOR_BORDER)
        sep.pack(fill="x", padx=8, pady=(0, 8))

        for icon, label in _NAV_ITEMS:
            btn = ctk.CTkButton(
                sidebar,
                text=f"  {icon}  {label}",
                anchor="w",
                height=36,
                corner_radius=8,
                fg_color="transparent",
                hover_color="#334155",
                text_color=COLOR_TEXT_MUTED,
                font=get_body_font(),
                command=lambda lbl=label: self._switch_tab(lbl),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_buttons[label] = btn

        # ── Right content area ───────────────────────────────────────────
        right = ctk.CTkFrame(outer, fg_color=COLOR_BG_WINDOW, corner_radius=0)
        right.pack(side="right", fill="both", expand=True)

        # Panels container
        self._panel_host = ctk.CTkFrame(right, fg_color="transparent")
        self._panel_host.pack(fill="both", expand=True, padx=0, pady=0)

        # Footer
        footer = ctk.CTkFrame(right, fg_color=COLOR_BG_CARD, height=52, corner_radius=0)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)

        f_inner = ctk.CTkFrame(footer, fg_color="transparent")
        f_inner.pack(fill="both", expand=True, padx=20, pady=8)

        ctk.CTkButton(
            f_inner, text="Cancel", width=90, height=34, corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.destroy,
        ).pack(side="left")

        ctk.CTkButton(
            f_inner,
            text=" Save Preferences",
            image=get_icon("check", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=160, height=34, corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            font=get_bold_font(),
            command=self._on_save,
        ).pack(side="right")

        # Build all panels (hidden by default) then show first tab
        self._build_panel_general()
        self._build_panel_downloads()
        self._build_panel_connection()
        self._build_panel_bittorrent()
        self._build_panel_network()
        self._build_panel_updates()

        self._switch_tab("General")

    def _switch_tab(self, label: str) -> None:
        # Hide all
        for name, panel in self._panels.items():
            panel.pack_forget()
        # Style nav buttons
        for name, btn in self._nav_buttons.items():
            if name == label:
                btn.configure(fg_color=COLOR_ACCENT, text_color=COLOR_TEXT_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=COLOR_TEXT_MUTED)
        # Show active
        self._panels[label].pack(fill="both", expand=True, padx=_PANEL_PAD_X, pady=_PANEL_PAD_Y)
        self._active_tab = label

    # -----------------------------------------------------------------------
    # Panel Builders — helpers
    # -----------------------------------------------------------------------

    def _make_panel(self, label: str) -> ctk.CTkScrollableFrame:
        panel = ctk.CTkScrollableFrame(
            self._panel_host,
            fg_color="transparent",
            scrollbar_button_color=COLOR_BORDER,
            scrollbar_button_hover_color=COLOR_ACCENT,
        )
        self._panels[label] = panel
        return panel

    @staticmethod
    def _section_header(parent, title: str) -> None:
        ctk.CTkLabel(parent, text=title, font=get_bold_font(), text_color=COLOR_ACCENT).pack(
            anchor="w", pady=(0, 6)
        )

    @staticmethod
    def _divider(parent) -> None:
        ctk.CTkFrame(parent, height=1, fg_color=COLOR_BORDER).pack(fill="x", pady=(_SECTION_GAP, _SECTION_GAP))

    @staticmethod
    def _row(parent) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=3)
        return f

    @staticmethod
    def _label(parent, text: str, muted: bool = False, side="left") -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(
            parent, text=text,
            font=get_body_font(),
            text_color=COLOR_TEXT_MUTED if muted else COLOR_TEXT_PRIMARY,
        )
        lbl.pack(side=side)
        return lbl

    # -----------------------------------------------------------------------
    # Panel: General
    # -----------------------------------------------------------------------

    def _build_panel_general(self) -> None:
        p = self._make_panel("General")

        # ── Startup ──────────────────────────────────────────────────────
        self._section_header(p, "STARTUP")

        self._startup_var = ctk.BooleanVar(value=get_run_on_startup())
        ctk.CTkCheckBox(
            p, text="Run Smart Download Manager on Windows startup (minimized to tray)",
            variable=self._startup_var, font=get_body_font(), text_color=COLOR_TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 4))

        self._divider(p)

        # ── Window Close ─────────────────────────────────────────────────
        self._section_header(p, "WINDOW CLOSE ACTION")

        stored_close = self.settings.get("close_action", "tray")
        self._close_var = ctk.StringVar(value=_rval(_CLOSE_LABELS, _CLOSE_VALUES, stored_close))
        for lbl in _CLOSE_LABELS:
            ctk.CTkRadioButton(
                p, text=lbl, variable=self._close_var, value=lbl,
                font=get_body_font(), text_color=COLOR_TEXT_PRIMARY,
            ).pack(anchor="w", pady=2)

        self._divider(p)

        # ── On Complete ──────────────────────────────────────────────────
        self._section_header(p, "DEFAULT ACTION WHEN DOWNLOAD COMPLETES")

        stored_complete = self.settings.get("on_complete_action", "notify")
        self._complete_menu = ctk.CTkOptionMenu(
            p,
            values=_COMPLETE_LABELS,
            height=_ROW_H,
            corner_radius=RADIUS_INPUT,
            fg_color=COLOR_BTN_SECONDARY,
        )
        self._complete_menu.set(_rval(_COMPLETE_LABELS, _COMPLETE_VALUES, stored_complete))
        self._complete_menu.pack(anchor="w", pady=(0, 4))

    # -----------------------------------------------------------------------
    # Panel: Downloads
    # -----------------------------------------------------------------------

    def _build_panel_downloads(self) -> None:
        p = self._make_panel("Downloads")

        # ── Download Directory ───────────────────────────────────────────
        self._section_header(p, "DOWNLOAD DIRECTORY")

        dest_row = self._row(p)
        self._dest_entry = ctk.CTkEntry(dest_row, height=_ROW_H, corner_radius=RADIUS_INPUT, font=get_body_font())
        self._dest_entry.insert(0, self.settings.get("dest_dir", "") or str(get_default_download_dir()))
        self._dest_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._dest_entry.bind("<KeyRelease>", lambda e: self._update_dl_preview())

        ctk.CTkButton(
            dest_row, text=" Browse",
            image=get_icon("folder", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left", width=90, height=_ROW_H, corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._on_browse,
        ).pack(side="right")

        ctk.CTkButton(
            p, text="Reset to System Default", width=160, height=28, corner_radius=RADIUS_BUTTON,
            fg_color="transparent", hover_color=COLOR_BTN_SECONDARY,
            text_color=COLOR_TEXT_MUTED, font=get_caption_font(),
            command=self._reset_dest_dir,
        ).pack(anchor="w", pady=(2, 0))

        self._divider(p)

        # ── Smart Categorization ─────────────────────────────────────────
        self._section_header(p, "SMART DOWNLOADER CATEGORIZATION")

        self._smart_var = ctk.BooleanVar(value=self.settings.get("use_smart_folders", True))
        ctk.CTkCheckBox(
            p,
            text="Organize downloads into Smart Downloader directory (by file type)",
            variable=self._smart_var,
            font=get_bold_font(), text_color=COLOR_TEXT_PRIMARY,
            command=self._update_dl_preview,
        ).pack(anchor="w")

        ctk.CTkLabel(
            p,
            text="Automatically sorts files into category folders: Images, Videos, Documents, Audio, Archives, Programs, Torrents",
            font=get_caption_font(), text_color=COLOR_TEXT_MUTED, justify="left", wraplength=580,
        ).pack(anchor="w", padx=24, pady=(2, 6))

        subrow = self._row(p)
        ctk.CTkLabel(subrow, text="Directory Name:", font=get_caption_font(), text_color=COLOR_TEXT_MUTED).pack(side="left", padx=(24, 8))
        self._smart_name_entry = ctk.CTkEntry(subrow, height=28, width=200, corner_radius=RADIUS_INPUT, font=get_caption_font())
        self._smart_name_entry.insert(0, self.settings.get("smart_folder_name", SMART_FOLDER_NAME))
        self._smart_name_entry.pack(side="left")
        self._smart_name_entry.bind("<KeyRelease>", lambda e: self._update_dl_preview())

        self._dl_preview_lbl = ctk.CTkLabel(p, text="", font=get_caption_font(), text_color=COLOR_ACCENT, justify="left")
        self._dl_preview_lbl.pack(anchor="w", padx=24, pady=(4, 0))
        self._update_dl_preview()

        self._divider(p)

        # ── Custom Categories ────────────────────────────────────────────
        self._section_header(p, "CUSTOM CATEGORY RULES")

        ctk.CTkLabel(
            p,
            text="Create personal categories beyond the built-in defaults (e.g. 3D Models, eBooks, Code).\n"
                 "Custom categories are checked before built-ins — files matching them go to their own subfolder.",
            font=get_caption_font(), text_color=COLOR_TEXT_MUTED, justify="left", wraplength=580,
        ).pack(anchor="w", pady=(0, 6))

        # Category list frame
        self._cat_list_frame = ctk.CTkFrame(p, fg_color=COLOR_BG_CARD, corner_radius=RADIUS_CARD, border_width=1, border_color=COLOR_BORDER)
        self._cat_list_frame.pack(fill="x", pady=(0, 8))
        self._refresh_custom_cat_list()

        btn_row = self._row(p)
        ctk.CTkButton(
            btn_row, text="+ New Custom Category", width=180, height=30, corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER, font=get_caption_font(),
            command=self._add_custom_category,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Reset to Defaults", width=140, height=30, corner_radius=RADIUS_BUTTON,
            fg_color="transparent", hover_color="#991b1b",
            text_color=COLOR_WARNING, font=get_caption_font(),
            command=self._reset_custom_categories,
        ).pack(side="right")

        self._divider(p)

        # ── Conflict Policy ──────────────────────────────────────────────
        self._section_header(p, "DUPLICATE FILE ACTION")

        stored_conflict = self.settings.get("file_conflict_policy", "rename")
        self._conflict_var = ctk.StringVar(value=_rval(_CONFLICT_LABELS, _CONFLICT_VALUES, stored_conflict))
        for lbl in _CONFLICT_LABELS:
            ctk.CTkRadioButton(
                p, text=lbl, variable=self._conflict_var, value=lbl,
                font=get_body_font(), text_color=COLOR_TEXT_PRIMARY,
            ).pack(anchor="w", pady=2)

        self._divider(p)

        # ── Auto-Start ───────────────────────────────────────────────────
        self._section_header(p, "QUEUE BEHAVIOR")
        self._autostart_var = ctk.BooleanVar(value=self.settings.get("auto_start", True))
        ctk.CTkCheckBox(
            p, text="Automatically start downloads immediately upon addition",
            variable=self._autostart_var, font=get_body_font(), text_color=COLOR_TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 4))

    # -- Downloads helpers ---------------------------------------------------

    def _update_dl_preview(self) -> None:
        dest = self._dest_entry.get().strip() or str(get_default_download_dir())
        subname = self._smart_name_entry.get().strip() or SMART_FOLDER_NAME
        if self._smart_var.get():
            self._dl_preview_lbl.configure(
                text=f"📂 Preview: {dest}\\{subname}\\<Category>  (e.g. \\Images)",
                text_color="#38bdf8",
            )
            self._smart_name_entry.configure(state="normal")
        else:
            self._dl_preview_lbl.configure(
                text=f"📂 Downloads will save directly into: {dest}",
                text_color=COLOR_TEXT_MUTED,
            )
            self._smart_name_entry.configure(state="disabled")

    def _on_browse(self) -> None:
        init_dir = self._dest_entry.get().strip() or str(get_default_download_dir())
        chosen = filedialog.askdirectory(initialdir=init_dir, parent=self)
        if chosen:
            self._dest_entry.delete(0, "end")
            self._dest_entry.insert(0, chosen)
            self._update_dl_preview()

    def _reset_dest_dir(self) -> None:
        self._dest_entry.delete(0, "end")
        self._dest_entry.insert(0, str(get_default_download_dir()))
        self._update_dl_preview()

    def _refresh_custom_cat_list(self) -> None:
        for w in self._cat_list_frame.winfo_children():
            w.destroy()

        if not self._custom_cats:
            ctk.CTkLabel(
                self._cat_list_frame,
                text="No custom categories yet — click '+ New Custom Category' to add one.",
                font=get_caption_font(), text_color=COLOR_TEXT_DIM,
            ).pack(padx=12, pady=10)
            return

        for idx, (name, exts) in enumerate(self._custom_cats):
            row = ctk.CTkFrame(self._cat_list_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=3)

            ctk.CTkLabel(
                row, text=f"📂 {name}",
                font=get_bold_font(), text_color=COLOR_TEXT_PRIMARY, width=160, anchor="w",
            ).pack(side="left")

            exts_str = ", ".join(exts)
            ctk.CTkLabel(
                row, text=exts_str,
                font=get_caption_font(), text_color=COLOR_TEXT_MUTED, anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=(4, 0))

            ctk.CTkButton(
                row, text="✏", width=28, height=24, corner_radius=6,
                fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER,
                font=get_caption_font(),
                command=lambda i=idx: self._edit_custom_category(i),
            ).pack(side="right", padx=(4, 0))
            ctk.CTkButton(
                row, text="✕", width=28, height=24, corner_radius=6,
                fg_color="transparent", hover_color="#991b1b",
                text_color=COLOR_WARNING, font=get_caption_font(),
                command=lambda i=idx: self._remove_custom_category(i),
            ).pack(side="right")

    def _add_custom_category(self) -> None:
        _CategoryEditorDialog(self, on_save=self._on_cat_editor_save)

    def _edit_custom_category(self, idx: int) -> None:
        name, exts = self._custom_cats[idx]
        def _save(new_name, new_exts_str):
            self._custom_cats[idx] = (new_name, [e.strip() for e in new_exts_str.split(",")])
            self._refresh_custom_cat_list()
        _CategoryEditorDialog(self, existing_name=name, existing_exts=", ".join(exts), on_save=_save)

    def _remove_custom_category(self, idx: int) -> None:
        del self._custom_cats[idx]
        self._refresh_custom_cat_list()

    def _reset_custom_categories(self) -> None:
        if messagebox.askyesno("Reset Categories", "Remove all custom categories?", parent=self):
            self._custom_cats.clear()
            self._refresh_custom_cat_list()

    def _on_cat_editor_save(self, name: str, exts_str: str) -> None:
        exts = [e.strip().lower() for e in exts_str.split(",") if e.strip()]
        self._custom_cats.append((name, exts))
        self._refresh_custom_cat_list()

    # -----------------------------------------------------------------------
    # Panel: Connection
    # -----------------------------------------------------------------------

    def _build_panel_connection(self) -> None:
        p = self._make_panel("Connection")

        self._section_header(p, "QUEUE CONCURRENCY")

        row = self._row(p)
        ctk.CTkLabel(row, text="Max Concurrent Active Downloads:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 12))
        self._conc_menu = ctk.CTkOptionMenu(
            row, values=["1", "2", "3", "4", "6", "8", "12"],
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY, width=100,
        )
        self._conc_menu.set(str(self.settings.get("max_concurrent", 2)))
        self._conc_menu.pack(side="left")

        row2 = self._row(p)
        ctk.CTkLabel(row2, text="Parallel Chunk Connections per file:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 12))
        self._conn_menu = ctk.CTkOptionMenu(
            row2, values=["1 (Single)", "2", "4", "6 (Recommended)", "8", "12", "16"],
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY, width=160,
        )
        stored_conn = self.settings.get("num_connections", 6)
        conn_map = {1: "1 (Single)", 2: "2", 4: "4", 6: "6 (Recommended)", 8: "8", 12: "12", 16: "16"}
        self._conn_menu.set(conn_map.get(stored_conn, "6 (Recommended)"))
        self._conn_menu.pack(side="left")

        self._divider(p)
        self._section_header(p, "CHUNKING THRESHOLD")

        row3 = self._row(p)
        ctk.CTkLabel(row3, text="Minimum file size for multi-chunk download:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 12))
        self._chunk_menu = ctk.CTkOptionMenu(
            row3, values=["10 MB", "25 MB", "50 MB", "100 MB"],
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY, width=120,
        )
        mb_map = {10: "10 MB", 25: "25 MB", 50: "50 MB", 100: "100 MB"}
        stored_mb = self.settings.get("chunk_threshold_mb", 50)
        self._chunk_menu.set(mb_map.get(stored_mb, "50 MB"))
        self._chunk_menu.pack(side="left")

        self._divider(p)
        self._section_header(p, "GLOBAL BANDWIDTH LIMITS")

        dl_row = self._row(p)
        self._dl_limit_var = ctk.BooleanVar(value=self.settings.get("speed_limit_dl_mbps", 0) > 0)
        ctk.CTkCheckBox(dl_row, text="Limit max download speed:", variable=self._dl_limit_var,
                        font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self._dl_limit_entry = ctk.CTkEntry(dl_row, width=70, height=28, corner_radius=RADIUS_INPUT)
        self._dl_limit_entry.insert(0, str(self.settings.get("speed_limit_dl_mbps", 0)))
        self._dl_limit_entry.pack(side="left")
        ctk.CTkLabel(dl_row, text="MB/s  (0 = Unlimited)", font=get_caption_font(), text_color=COLOR_TEXT_MUTED).pack(side="left", padx=6)

        ul_row = self._row(p)
        self._ul_limit_var = ctk.BooleanVar(value=self.settings.get("speed_limit_ul_kbps", 0) > 0)
        ctk.CTkCheckBox(ul_row, text="Limit max upload speed:", variable=self._ul_limit_var,
                        font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self._ul_limit_entry = ctk.CTkEntry(ul_row, width=70, height=28, corner_radius=RADIUS_INPUT)
        self._ul_limit_entry.insert(0, str(self.settings.get("speed_limit_ul_kbps", 0)))
        self._ul_limit_entry.pack(side="left")
        ctk.CTkLabel(ul_row, text="KB/s  (0 = Unlimited)", font=get_caption_font(), text_color=COLOR_TEXT_MUTED).pack(side="left", padx=6)

    # -----------------------------------------------------------------------
    # Panel: BitTorrent
    # -----------------------------------------------------------------------

    def _build_panel_bittorrent(self) -> None:
        p = self._make_panel("BitTorrent")

        self._section_header(p, "LISTENING PORT")

        port_row = self._row(p)
        self._torrent_rand_var = ctk.BooleanVar(value=self.settings.get("torrent_random_port", False))
        ctk.CTkCheckBox(port_row, text="Use random port on each startup",
                        variable=self._torrent_rand_var, font=get_body_font(),
                        text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(port_row, text="Port:", font=get_body_font(), text_color=COLOR_TEXT_MUTED).pack(side="left", padx=(0, 6))
        self._torrent_port_entry = ctk.CTkEntry(port_row, width=80, height=28, corner_radius=RADIUS_INPUT)
        self._torrent_port_entry.insert(0, str(self.settings.get("torrent_port", 6881)))
        self._torrent_port_entry.pack(side="left")

        self._divider(p)
        self._section_header(p, "SEEDING")

        seed_row = self._row(p)
        ctk.CTkLabel(seed_row, text="Stop seeding when ratio reaches:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self._seed_ratio_menu = ctk.CTkOptionMenu(
            seed_row, values=["0.5", "1.0", "1.5", "2.0", "5.0", "Unlimited"],
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY, width=120,
        )
        stored_ratio = self.settings.get("seeding_ratio_limit", 1.0)
        ratio_str = str(stored_ratio) if stored_ratio > 0 else "Unlimited"
        self._seed_ratio_menu.set(ratio_str if ratio_str in ["0.5", "1.0", "1.5", "2.0", "5.0", "Unlimited"] else "1.0")
        self._seed_ratio_menu.pack(side="left")

        self._divider(p)
        self._section_header(p, "DISCOVERY PROTOCOLS")

        self._dht_var = ctk.BooleanVar(value=self.settings.get("dht_enabled", True))
        ctk.CTkCheckBox(p, text="Distributed Hash Table (DHT) — enables finding peers without tracker",
                        variable=self._dht_var, font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(anchor="w", pady=2)

        self._pex_var = ctk.BooleanVar(value=self.settings.get("pex_enabled", True))
        ctk.CTkCheckBox(p, text="Peer Exchange (PeX) — share peer lists between connected peers",
                        variable=self._pex_var, font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(anchor="w", pady=2)

        self._lsd_var = ctk.BooleanVar(value=self.settings.get("lsd_enabled", True))
        ctk.CTkCheckBox(p, text="Local Peer Discovery (LSD) — find peers on the same LAN",
                        variable=self._lsd_var, font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(anchor="w", pady=2)

        self._divider(p)
        self._section_header(p, "PROTOCOL ENCRYPTION")

        stored_enc = self.settings.get("protocol_encryption", "enabled")
        self._enc_menu = ctk.CTkOptionMenu(
            p, values=_ENC_LABELS,
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY,
        )
        self._enc_menu.set(_rval(_ENC_LABELS, _ENC_VALUES, stored_enc))
        self._enc_menu.pack(anchor="w", pady=(0, 4))

    # -----------------------------------------------------------------------
    # Panel: Network
    # -----------------------------------------------------------------------

    def _build_panel_network(self) -> None:
        p = self._make_panel("Network")

        self._section_header(p, "PROXY CONFIGURATION")

        # Proxy mode radio buttons
        self._proxy_mode_var = ctk.StringVar(value=self.settings.get("proxy_mode", "none"))
        for val, lbl in [("none", "No Proxy (Direct connection)"), ("system", "Use System / Windows Proxy"), ("manual", "Manual Proxy (HTTP / SOCKS5)")]:
            ctk.CTkRadioButton(
                p, text=lbl, variable=self._proxy_mode_var, value=val,
                font=get_body_font(), text_color=COLOR_TEXT_PRIMARY,
                command=self._toggle_proxy_fields,
            ).pack(anchor="w", pady=2)

        # Manual proxy fields
        self._proxy_fields_frame = ctk.CTkFrame(p, fg_color=COLOR_BG_CARD, corner_radius=RADIUS_CARD, border_width=1, border_color=COLOR_BORDER)
        self._proxy_fields_frame.pack(fill="x", pady=(8, 0), padx=16)

        pf = ctk.CTkFrame(self._proxy_fields_frame, fg_color="transparent")
        pf.pack(fill="x", padx=12, pady=10)

        # Type
        trow = self._row(pf)
        ctk.CTkLabel(trow, text="Type:", font=get_caption_font(), text_color=COLOR_TEXT_MUTED, width=80, anchor="w").pack(side="left")
        self._proxy_type_menu = ctk.CTkOptionMenu(trow, values=["http", "socks5"], width=100, height=26, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY)
        self._proxy_type_menu.set(self.settings.get("proxy_type", "http"))
        self._proxy_type_menu.pack(side="left")

        # Host & Port
        hrow = self._row(pf)
        ctk.CTkLabel(hrow, text="Host:", font=get_caption_font(), text_color=COLOR_TEXT_MUTED, width=80, anchor="w").pack(side="left")
        self._proxy_host_entry = ctk.CTkEntry(hrow, width=200, height=26, corner_radius=RADIUS_INPUT, font=get_caption_font())
        self._proxy_host_entry.insert(0, self.settings.get("proxy_host", ""))
        self._proxy_host_entry.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(hrow, text="Port:", font=get_caption_font(), text_color=COLOR_TEXT_MUTED).pack(side="left")
        self._proxy_port_entry = ctk.CTkEntry(hrow, width=70, height=26, corner_radius=RADIUS_INPUT, font=get_caption_font())
        self._proxy_port_entry.insert(0, str(self.settings.get("proxy_port", 8080)))
        self._proxy_port_entry.pack(side="left", padx=(4, 0))

        # User & Pass
        urow = self._row(pf)
        ctk.CTkLabel(urow, text="Username:", font=get_caption_font(), text_color=COLOR_TEXT_MUTED, width=80, anchor="w").pack(side="left")
        self._proxy_user_entry = ctk.CTkEntry(urow, width=160, height=26, corner_radius=RADIUS_INPUT, font=get_caption_font())
        self._proxy_user_entry.insert(0, self.settings.get("proxy_username", ""))
        self._proxy_user_entry.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(urow, text="Password:", font=get_caption_font(), text_color=COLOR_TEXT_MUTED).pack(side="left")
        self._proxy_pass_entry = ctk.CTkEntry(urow, width=120, height=26, corner_radius=RADIUS_INPUT, font=get_caption_font(), show="*")
        self._proxy_pass_entry.insert(0, self.settings.get("proxy_password", ""))
        self._proxy_pass_entry.pack(side="left", padx=(4, 0))

        self._toggle_proxy_fields()  # initial state

        self._divider(p)
        self._section_header(p, "EXTENSION BRIDGE SERVER")

        brow = self._row(p)
        ctk.CTkLabel(brow, text="Bridge listening port:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self._bridge_port_entry = ctk.CTkEntry(brow, width=80, height=_ROW_H, corner_radius=RADIUS_INPUT)
        self._bridge_port_entry.insert(0, str(self.settings.get("bridge_port", 8992)))
        self._bridge_port_entry.pack(side="left")
        ctk.CTkLabel(brow, text="(requires app restart to take effect)", font=get_caption_font(), text_color=COLOR_TEXT_MUTED).pack(side="left", padx=8)

        self._divider(p)
        self._section_header(p, "AUTO-RETRY & RESILIENCE")

        rrow = self._row(p)
        ctk.CTkLabel(rrow, text="Max automatic reconnect retries:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self._retry_menu = ctk.CTkOptionMenu(
            rrow, values=["3", "5", "10", "Unlimited"],
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY, width=120,
        )
        stored_retry = self.settings.get("max_retries", 5)
        retry_map = {3: "3", 5: "5", 10: "10", 0: "Unlimited"}
        self._retry_menu.set(retry_map.get(stored_retry, "5"))
        self._retry_menu.pack(side="left")

        brow2 = self._row(p)
        ctk.CTkLabel(brow2, text="Retry backoff interval:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self._backoff_menu = ctk.CTkOptionMenu(
            brow2, values=["2s", "5s", "10s"],
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY, width=100,
        )
        backoff_map = {2: "2s", 5: "5s", 10: "10s"}
        self._backoff_menu.set(backoff_map.get(self.settings.get("retry_backoff", 5), "5s"))
        self._backoff_menu.pack(side="left")

    def _toggle_proxy_fields(self) -> None:
        is_manual = self._proxy_mode_var.get() == "manual"
        state = "normal" if is_manual else "disabled"
        for child in [self._proxy_type_menu, self._proxy_host_entry,
                       self._proxy_port_entry, self._proxy_user_entry, self._proxy_pass_entry]:
            try:
                child.configure(state=state)
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Panel: Updates
    # -----------------------------------------------------------------------

    def _build_panel_updates(self) -> None:
        p = self._make_panel("Updates")

        self._section_header(p, "CURRENT VERSION")

        from updater import CURRENT_VERSION
        ver_row = self._row(p)
        ctk.CTkLabel(
            ver_row,
            text=f"Smart Download Manager  v{CURRENT_VERSION}",
            font=get_bold_font(), text_color=COLOR_TEXT_PRIMARY,
        ).pack(side="left")

        ctk.CTkButton(
            ver_row, text="View on GitHub →", width=130, height=26, corner_radius=RADIUS_BUTTON,
            fg_color="transparent", hover_color=COLOR_BTN_SECONDARY,
            text_color=COLOR_ACCENT, font=get_caption_font(),
            command=lambda: webbrowser.open("https://github.com/Bensonmusonda/my-download-manager/releases"),
        ).pack(side="right")

        self._divider(p)
        self._section_header(p, "AUTOMATIC UPDATES")

        self._auto_update_var = ctk.BooleanVar(value=self.settings.get("auto_check_updates", True))
        ctk.CTkCheckBox(
            p, text="Automatically check for updates on startup",
            variable=self._auto_update_var, font=get_body_font(), text_color=COLOR_TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 6))

        chan_row = self._row(p)
        ctk.CTkLabel(chan_row, text="Update channel:", font=get_body_font(), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(0, 8))
        self._update_channel_menu = ctk.CTkOptionMenu(
            chan_row, values=["Stable Releases", "Pre-releases (beta)"],
            height=_ROW_H, corner_radius=RADIUS_INPUT, fg_color=COLOR_BTN_SECONDARY, width=200,
        )
        self._update_channel_menu.set(
            "Pre-releases (beta)" if self.settings.get("update_channel", "stable") == "prerelease"
            else "Stable Releases"
        )
        self._update_channel_menu.pack(side="left")

        self._divider(p)
        self._section_header(p, "MANUAL CHECK")

        check_btn = ctk.CTkButton(
            p,
            text="  🔄  Check for Updates Now",
            height=38, corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER,
            font=get_bold_font(),
            command=self._run_manual_update_check,
        )
        check_btn.pack(anchor="w", pady=(0, 10))
        self._check_btn = check_btn

        self._update_status_lbl = ctk.CTkLabel(
            p, text="", font=get_caption_font(), text_color=COLOR_TEXT_MUTED, justify="left"
        )
        self._update_status_lbl.pack(anchor="w")

    def _run_manual_update_check(self) -> None:
        self._check_btn.configure(state="disabled", text="  ⏳  Checking…")
        self._update_status_lbl.configure(text="Contacting GitHub…", text_color=COLOR_TEXT_MUTED)

        channel = self._update_channel_menu.get()
        include_pre = "Pre-releases" in channel

        def _worker():
            from updater import UpdateChecker, CURRENT_VERSION
            try:
                info = UpdateChecker.check_for_updates(CURRENT_VERSION, include_prereleases=include_pre)
                self.after(0, lambda: self._on_update_result(info, None))
            except Exception as exc:
                self.after(0, lambda: self._on_update_result(None, str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_result(self, info, error: Optional[str]) -> None:
        try:
            self._check_btn.configure(state="normal", text="  🔄  Check for Updates Now")
        except Exception:
            return

        if error:
            self._update_status_lbl.configure(
                text=f"⚠ Could not reach GitHub: {error}", text_color=COLOR_WARNING
            )
            return

        if info is None:
            self._update_status_lbl.configure(
                text="✅  You're up to date!", text_color=COLOR_SUCCESS
            )
        else:
            self._update_status_lbl.configure(
                text=f"🆕  v{info.remote_version} is available — published {info.published_at[:10]}",
                text_color="#38bdf8",
            )
            self._show_update_available_dialog(info)

    def _show_update_available_dialog(self, info) -> None:
        """Show a simple messagebox; a richer modal can be added in a later sprint."""
        from updater import CURRENT_VERSION
        notes_preview = (info.release_notes or "")[:800]
        msg = (
            f"A new version is available!\n\n"
            f"  Current:  v{CURRENT_VERSION}\n"
            f"  Latest:   v{info.remote_version}\n\n"
            f"Release notes:\n{notes_preview}\n\n"
            "Open the GitHub release page to download?"
        )
        ans = messagebox.askyesno("Update Available", msg, parent=self)
        if ans:
            webbrowser.open(info.html_url)

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    def _on_save(self) -> None:
        # ── General ──────────────────────────────────────────────────────
        close_label = self._close_var.get()
        close_val = _CLOSE_VALUES[_CLOSE_LABELS.index(close_label)] if close_label in _CLOSE_LABELS else "tray"
        complete_label = self._complete_menu.get()
        complete_val = _COMPLETE_VALUES[_COMPLETE_LABELS.index(complete_label)] if complete_label in _COMPLETE_LABELS else "notify"

        startup_enabled = self._startup_var.get()
        set_run_on_startup(startup_enabled)

        # ── Downloads ────────────────────────────────────────────────────
        dest = self._dest_entry.get().strip() or str(get_default_download_dir())
        smart_name = self._smart_name_entry.get().strip() or SMART_FOLDER_NAME
        conflict_label = self._conflict_var.get()
        conflict_val = _CONFLICT_VALUES[_CONFLICT_LABELS.index(conflict_label)] if conflict_label in _CONFLICT_LABELS else "rename"
        custom_cats_dict = {name: exts for name, exts in self._custom_cats}

        # ── Connection ───────────────────────────────────────────────────
        c_val = int(self._conc_menu.get())
        conn_str = self._conn_menu.get()
        try:
            conn_int = int(conn_str.split()[0])
        except Exception:
            conn_int = 6
        chunk_mb = int(self._chunk_menu.get().split()[0])

        try:
            dl_limit = float(self._dl_limit_entry.get()) if self._dl_limit_var.get() else 0
        except ValueError:
            dl_limit = 0
        try:
            ul_limit = float(self._ul_limit_entry.get()) if self._ul_limit_var.get() else 0
        except ValueError:
            ul_limit = 0

        # ── BitTorrent ───────────────────────────────────────────────────
        try:
            torrent_port = int(self._torrent_port_entry.get())
        except ValueError:
            torrent_port = 6881

        ratio_str = self._seed_ratio_menu.get()
        try:
            seeding_ratio = float(ratio_str) if ratio_str != "Unlimited" else 0.0
        except ValueError:
            seeding_ratio = 1.0

        enc_label = self._enc_menu.get()
        enc_val = _ENC_VALUES[_ENC_LABELS.index(enc_label)] if enc_label in _ENC_LABELS else "enabled"

        # ── Network ──────────────────────────────────────────────────────
        try:
            bridge_port = int(self._bridge_port_entry.get())
        except ValueError:
            bridge_port = 8992

        retry_str = self._retry_menu.get()
        retry_map = {"3": 3, "5": 5, "10": 10, "Unlimited": 0}
        max_retries = retry_map.get(retry_str, 5)

        backoff_str = self._backoff_menu.get()
        backoff_map = {"2s": 2, "5s": 5, "10s": 10}
        retry_backoff = backoff_map.get(backoff_str, 5)

        try:
            proxy_port_val = int(self._proxy_port_entry.get())
        except ValueError:
            proxy_port_val = 8080

        # ── Updates ──────────────────────────────────────────────────────
        import time as _time
        update_channel = "prerelease" if "Pre-releases" in self._update_channel_menu.get() else "stable"

        new_settings = {
            # General
            "run_on_startup": startup_enabled,
            "close_action": close_val,
            "on_complete_action": complete_val,
            # Downloads
            "dest_dir": dest,
            "use_smart_folders": self._smart_var.get(),
            "smart_folder_name": smart_name,
            "file_conflict_policy": conflict_val,
            "auto_start": self._autostart_var.get(),
            "custom_categories": custom_cats_dict,
            # Connection
            "max_concurrent": c_val,
            "num_connections": conn_int,
            "chunk_threshold_mb": chunk_mb,
            "speed_limit_dl_mbps": dl_limit,
            "speed_limit_ul_kbps": ul_limit,
            # BitTorrent
            "torrent_port": torrent_port,
            "torrent_random_port": self._torrent_rand_var.get(),
            "seeding_ratio_limit": seeding_ratio,
            "dht_enabled": self._dht_var.get(),
            "pex_enabled": self._pex_var.get(),
            "lsd_enabled": self._lsd_var.get(),
            "protocol_encryption": enc_val,
            # Network
            "proxy_mode": self._proxy_mode_var.get(),
            "proxy_type": self._proxy_type_menu.get(),
            "proxy_host": self._proxy_host_entry.get().strip(),
            "proxy_port": proxy_port_val,
            "proxy_username": self._proxy_user_entry.get().strip(),
            "proxy_password": self._proxy_pass_entry.get(),
            "bridge_port": bridge_port,
            "max_retries": max_retries,
            "retry_backoff": retry_backoff,
            # Updates
            "auto_check_updates": self._auto_update_var.get(),
            "update_channel": update_channel,
            "last_update_check_ts": self.settings.get("last_update_check_ts", 0.0),
            # Preserve minimize_to_tray from close_action for backward compat
            "minimize_to_tray": close_val == "tray",
        }

        self.on_save(new_settings)
        self.destroy()
