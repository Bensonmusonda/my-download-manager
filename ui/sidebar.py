"""
Navigation Sidebar Component for Smart Download Manager.
Fixed width 200px, category filtering, live count badges, and protocol filters.
Strictly adheres to Section 4.3 Component A of HANDOFF.md.
"""

from __future__ import annotations

from typing import Callable, Dict
import customtkinter as ctk

from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_SIDEBAR,
    COLOR_BG_CARD,
    COLOR_BG_CARD_HOVER,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_DIM,
    COLOR_ACCENT,
    COLOR_SUCCESS,
    COLOR_WARNING,
    COLOR_TORRENT,
    COLOR_WEB,
    RADIUS_CARD,
    RADIUS_PILL,
    get_title_font,
    get_section_font,
    get_bold_font,
    get_body_font,
    get_badge_font,
    get_caption_font,
)


class SidebarItem(ctk.CTkFrame):
    """Single interactive navigation item with left accent indicator and count badge."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        key: str,
        label: str,
        icon_name: str,
        icon_color: str,
        on_click: Callable[[str], None],
        show_icon: bool = True,
    ):
        super().__init__(parent, fg_color="transparent", corner_radius=RADIUS_CARD, height=36)
        self.key = key
        self.label_text = label
        self.icon_name = icon_name
        self.icon_color = icon_color
        self.on_click = on_click
        self.is_selected = False

        self.pack_propagate(False)

        # 3px Left selection indicator bar
        self.indicator = ctk.CTkFrame(
            self,
            width=3,
            corner_radius=1,
            fg_color="transparent",
        )
        self.indicator.pack(side="left", fill="y", padx=(2, 6), pady=4)

        # Icon (optional — hidden for Downloads / Protocols sections)
        self.icon_lbl: ctk.CTkLabel | None = None
        if show_icon:
            self.icon_lbl = ctk.CTkLabel(
                self,
                text="",
                image=get_icon(icon_name, icon_color, (16, 16)),
                width=20,
            )
            self.icon_lbl.pack(side="left", padx=(0, 8))

        # Title
        self.title_lbl = ctk.CTkLabel(
            self,
            text=label,
            font=get_body_font(),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.title_lbl.pack(side="left", fill="x", expand=True)

        # Count Badge (Pill)
        self.badge = ctk.CTkLabel(
            self,
            text="",
            font=get_badge_font(),
            text_color=COLOR_TEXT_DIM,
            fg_color="transparent",
            corner_radius=RADIUS_PILL,
            padx=6,
            height=18,
        )
        self.badge.pack(side="right", padx=(0, 8))

        # Event bindings
        bindable = [self, self.indicator, self.title_lbl, self.badge]
        if self.icon_lbl:
            bindable.append(self.icon_lbl)
        for widget in bindable:
            widget.bind("<Button-1>", lambda e: self.on_click(self.key))
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    def set_selected(self, selected: bool) -> None:
        self.is_selected = selected
        if selected:
            self.configure(fg_color=COLOR_BG_CARD)
            self.indicator.configure(fg_color=COLOR_ACCENT)
            self.title_lbl.configure(text_color=COLOR_TEXT_PRIMARY, font=get_bold_font())
        else:
            self.configure(fg_color="transparent")
            self.indicator.configure(fg_color="transparent")
            self.title_lbl.configure(text_color=COLOR_TEXT_MUTED, font=get_body_font())

    def update_badge(self, count: int, highlight_color: str | None = None) -> None:
        if count <= 0:
            self.badge.configure(text="", fg_color="transparent")
        else:
            self.badge.configure(text=str(count))
            if highlight_color:
                self.badge.configure(fg_color=highlight_color, text_color=COLOR_TEXT_PRIMARY)
            else:
                self.badge.configure(fg_color=COLOR_BORDER, text_color=COLOR_TEXT_PRIMARY)

    def _on_enter(self, event=None) -> None:
        if not self.is_selected:
            self.configure(fg_color=COLOR_BG_CARD_HOVER)

    def _on_leave(self, event=None) -> None:
        if not self.is_selected:
            self.configure(fg_color="transparent")


class NavigationSidebar(ctk.CTkFrame):
    """200px Fixed Navigation Sidebar."""

    def __init__(
        self,
        parent: ctk.CTk,
        on_filter_changed: Callable[[str], None],
        on_open_recovery: Callable[[], None],
        on_open_settings: Callable[[], None],
    ):
        super().__init__(
            parent,
            width=200,
            corner_radius=0,
            fg_color=COLOR_BG_SIDEBAR,
            border_width=0,
        )
        self.on_filter_changed = on_filter_changed
        self.on_open_recovery = on_open_recovery
        self.on_open_settings = on_open_settings
        self.items: Dict[str, SidebarItem] = {}
        self.current_filter = "all"

        self.pack_propagate(False)
        self._build_sidebar()

    def _build_sidebar(self) -> None:
        # Right border — 1px vertical line on the trailing edge of the sidebar
        right_border = ctk.CTkFrame(self, width=1, fg_color=COLOR_BORDER, corner_radius=0)
        right_border.pack(side="right", fill="y")
        # Top Branding
        brand_frame = ctk.CTkFrame(self, fg_color="transparent", height=54)
        brand_frame.pack(fill="x", padx=14, pady=(12, 10))
        brand_frame.pack_propagate(False)

        logo_lbl = ctk.CTkLabel(
            brand_frame,
            text="",
            image=get_icon("logo", COLOR_ACCENT, (26, 26)),
        )
        logo_lbl.pack(side="left", padx=(0, 10))

        text_frame = ctk.CTkFrame(brand_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True)

        app_title = ctk.CTkLabel(
            text_frame,
            text="Smart Downloader",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        app_title.pack(anchor="w")

        version_badge = ctk.CTkLabel(
            text_frame,
            text="v1.1.0 Pro",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        version_badge.pack(anchor="w")

        # Divider
        div1 = ctk.CTkFrame(self, height=1, fg_color=COLOR_BORDER)
        div1.pack(fill="x", padx=12, pady=(0, 10))

        # Section 1: DOWNLOADS
        sec1_lbl = ctk.CTkLabel(
            self,
            text="DOWNLOADS",
            font=get_badge_font(),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        )
        sec1_lbl.pack(fill="x", padx=16, pady=(4, 6))

        dl_categories = [
            ("all", "All Downloads", "download", COLOR_TEXT_PRIMARY),
            ("downloading", "Downloading", "arrow_down", COLOR_SUCCESS),
            ("paused", "Paused", "pause", COLOR_WARNING),
            ("expired", "Expired", "warning", COLOR_WARNING),
            ("completed", "Completed", "check", COLOR_SUCCESS),
        ]

        for key, label, icon, color in dl_categories:
            item = SidebarItem(self, key, label, icon, color, self._on_item_clicked, show_icon=False)
            item.pack(fill="x", padx=8, pady=1)
            self.items[key] = item

        # Section 2: PROTOCOLS
        sec2_lbl = ctk.CTkLabel(
            self,
            text="PROTOCOLS",
            font=get_badge_font(),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        )
        sec2_lbl.pack(fill="x", padx=16, pady=(16, 6))

        proto_categories = [
            ("http", "Direct Web", "web", COLOR_WEB),
            ("torrents", "BitTorrent", "torrent", COLOR_TORRENT),
        ]

        for key, label, icon, color in proto_categories:
            item = SidebarItem(self, key, label, icon, color, self._on_item_clicked, show_icon=False)
            item.pack(fill="x", padx=8, pady=1)
            self.items[key] = item

        # Bottom Utilities (Pinned to bottom)
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(side="bottom", fill="x", padx=8, pady=12)

        div2 = ctk.CTkFrame(bottom_frame, height=1, fg_color=COLOR_BORDER)
        div2.pack(fill="x", padx=4, pady=(0, 8))

        sec3_lbl = ctk.CTkLabel(
            bottom_frame,
            text="UTILITIES",
            font=get_badge_font(),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        )
        sec3_lbl.pack(fill="x", padx=8, pady=(0, 4))

        recovery_btn = SidebarItem(
            bottom_frame,
            "recovery",
            "Disk Recovery",
            "recovery",
            COLOR_WEB,
            lambda k: self.on_open_recovery(),
        )
        recovery_btn.pack(fill="x", pady=1)
        self.items["recovery"] = recovery_btn

        settings_btn = SidebarItem(
            bottom_frame,
            "settings",
            "Preferences",
            "settings",
            COLOR_TEXT_MUTED,
            lambda k: self.on_open_settings(),
        )
        settings_btn.pack(fill="x", pady=1)
        self.items["settings"] = settings_btn

        # Set default selection
        self.set_active_filter("all")

    def _on_item_clicked(self, key: str) -> None:
        self.set_active_filter(key)
        self.on_filter_changed(key)

    def set_active_filter(self, key: str) -> None:
        self.current_filter = key
        for k, item in self.items.items():
            item.set_selected(k == key)

    def update_counts(
        self,
        total: int,
        downloading: int,
        paused: int,
        expired: int,
        completed: int,
        http_count: int,
        torrent_count: int,
    ) -> None:
        """Update live count badges on sidebar items."""
        if "all" in self.items:
            self.items["all"].update_badge(total)
        if "downloading" in self.items:
            self.items["downloading"].update_badge(downloading, highlight_color=COLOR_SUCCESS if downloading > 0 else None)
        if "paused" in self.items:
            self.items["paused"].update_badge(paused)
        if "expired" in self.items:
            self.items["expired"].update_badge(expired, highlight_color=COLOR_WARNING if expired > 0 else None)
        if "completed" in self.items:
            self.items["completed"].update_badge(completed)
        if "http" in self.items:
            self.items["http"].update_badge(http_count)
        if "torrents" in self.items:
            self.items["torrents"].update_badge(torrent_count)
