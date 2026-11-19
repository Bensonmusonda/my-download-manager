"""
Top Toolbar Strip Component for Smart Download Manager.
Features horizontal scrollability when items don't fit (without visible scrollbars),
neutral aesthetic matching dark gray theme, icon-only buttons with tooltips for
Resume All, Pause All, and Clear Done (with check-check icon instead of trash bin).
"""

from __future__ import annotations

from typing import Callable
import customtkinter as ctk

from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_ACCENT,
    COLOR_ACCENT_HOVER,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    RADIUS_BUTTON,
    RADIUS_INPUT,
    get_bold_font,
    get_caption_font,
)
from ui.tooltip import Tooltip


class TopToolbar(ctk.CTkFrame):
    """54px Top Toolbar Strip with hidden-scrollbar horizontal scroll capability."""

    def __init__(
        self,
        parent: ctk.CTk,
        on_add_download: Callable[[], None],
        on_add_torrent: Callable[[], None],
        on_batch_ingest: Callable[[], None],
        on_resume_all: Callable[[], None],
        on_pause_all: Callable[[], None],
        on_clear_completed: Callable[[], None],
        on_search_query: Callable[[str], None],
        on_concurrency_changed: Callable[[int], None],
        initial_concurrency: int = 2,
    ):
        super().__init__(
            parent,
            height=54,
            corner_radius=0,
            fg_color=COLOR_BG_CARD,
            border_width=0,
        )
        self.on_add_download = on_add_download
        self.on_add_torrent = on_add_torrent
        self.on_batch_ingest = on_batch_ingest
        self.on_resume_all = on_resume_all
        self.on_pause_all = on_pause_all
        self.on_clear_completed = on_clear_completed
        self.on_search_query = on_search_query
        self.on_concurrency_changed = on_concurrency_changed
        self.initial_concurrency = initial_concurrency

        self.pack_propagate(False)
        self._build_toolbar()

    def _build_toolbar(self) -> None:
        # Horizontally scrollable frame so contents never get cut off on narrow screens
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            orientation="horizontal",
            height=54,
            fg_color="transparent",
            corner_radius=0,
        )
        self.scroll_frame.pack(fill="both", expand=True)

        # Hide the horizontal scrollbar completely (no scrollbar requested)
        if hasattr(self.scroll_frame, "_scrollbar"):
            self.scroll_frame._scrollbar.grid_forget()

        # Inner container holding all buttons (naturally expands horizontally)
        container = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        container.pack(side="left", fill="y", padx=12, pady=8)

        # ── Left Group: Action Triggers ───────────────────────────────
        add_btn = ctk.CTkButton(
            container,
            text=" Add Download",
            image=get_icon("plus", COLOR_TEXT_PRIMARY, (15, 15)),
            compound="left",
            font=get_bold_font(),
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            command=self.on_add_download,
        )
        add_btn.pack(side="left", padx=(0, 8))

        torrent_btn = ctk.CTkButton(
            container,
            text=" Add Torrent",
            image=get_icon("torrent", COLOR_TEXT_PRIMARY, (15, 15)),
            compound="left",
            font=get_bold_font(),
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.on_add_torrent,
        )
        torrent_btn.pack(side="left", padx=(0, 8))

        batch_btn = ctk.CTkButton(
            container,
            text=" Batch Ingestion",
            image=get_icon("batch", COLOR_TEXT_PRIMARY, (15, 15)),
            compound="left",
            font=get_bold_font(),
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.on_batch_ingest,
        )
        batch_btn.pack(side="left", padx=(0, 12))

        # Vertical Divider
        div1 = ctk.CTkFrame(container, width=1, fg_color=COLOR_BORDER)
        div1.pack(side="left", fill="y", padx=(0, 12), pady=4)

        # ── Middle Group: Compact Queue Controls (Icons only + Tooltips) ───
        resume_all_btn = ctk.CTkButton(
            container,
            text="",
            image=get_icon("play", COLOR_TEXT_PRIMARY, (15, 15)),
            width=36,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.on_resume_all,
        )
        resume_all_btn.pack(side="left", padx=(0, 6))
        Tooltip(resume_all_btn, "Resume All Downloads")

        pause_all_btn = ctk.CTkButton(
            container,
            text="",
            image=get_icon("pause", COLOR_TEXT_PRIMARY, (15, 15)),
            width=36,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.on_pause_all,
        )
        pause_all_btn.pack(side="left", padx=(0, 6))
        Tooltip(pause_all_btn, "Pause All Downloads")

        clear_btn = ctk.CTkButton(
            container,
            text="",
            image=get_icon("check_check", COLOR_TEXT_MUTED, (16, 16)),
            width=36,
            height=36,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self.on_clear_completed,
        )
        clear_btn.pack(side="left", padx=(0, 12))
        Tooltip(clear_btn, "Clear Completed Downloads")

        # Vertical Divider
        div2 = ctk.CTkFrame(container, width=1, fg_color=COLOR_BORDER)
        div2.pack(side="left", fill="y", padx=(0, 12), pady=4)

        # ── Right Group: Search & Concurrency ─────────────────────────
        # Search Entry with icon
        search_frame = ctk.CTkFrame(container, fg_color="transparent")
        search_frame.pack(side="left", padx=(0, 12))

        search_icon = ctk.CTkLabel(
            search_frame,
            text="",
            image=get_icon("search", COLOR_TEXT_MUTED, (14, 14)),
        )
        search_icon.pack(side="left", padx=(0, 4))

        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="Filter downloads...",
            width=180,
            height=34,
            corner_radius=RADIUS_INPUT,
            font=get_bold_font(),
        )
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        # Concurrency Menu
        conc_frame = ctk.CTkFrame(container, fg_color="transparent")
        conc_frame.pack(side="left")

        conc_lbl = ctk.CTkLabel(
            conc_frame,
            text="Concurrency:",
            font=get_bold_font(),
            text_color=COLOR_TEXT_MUTED,
        )
        conc_lbl.pack(side="left", padx=(0, 6))

        self.conc_menu = ctk.CTkOptionMenu(
            conc_frame,
            values=["1", "2", "3", "4", "6"],
            width=65,
            height=34,
            corner_radius=RADIUS_INPUT,
            font=get_bold_font(),
            fg_color=COLOR_BTN_SECONDARY,
            button_color=COLOR_BTN_SECONDARY,
            button_hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._on_concurrency_menu_changed,
        )
        self.conc_menu.set(str(self.initial_concurrency))
        self.conc_menu.pack(side="left")

        # Enable smooth horizontal mousewheel scrolling on the toolbar
        self._bind_mousewheel(self)

    def _bind_mousewheel(self, widget) -> None:
        canvas = getattr(self.scroll_frame, "_parent_canvas", None)
        if canvas:
            def _scroll(event):
                # Scroll horizontally on mousewheel
                delta = int(-1 * (event.delta / 120)) if event.delta else 0
                canvas.xview_scroll(delta, "units")

            widget.bind("<MouseWheel>", _scroll, add="+")
            widget.bind("<Shift-MouseWheel>", _scroll, add="+")
            for child in widget.winfo_children():
                self._bind_mousewheel(child)

    def _on_search_key(self, event=None) -> None:
        query = self.search_entry.get().strip()
        self.on_search_query(query)

    def _on_concurrency_menu_changed(self, value: str) -> None:
        try:
            val = int(value)
            self.on_concurrency_changed(val)
        except ValueError:
            pass

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
