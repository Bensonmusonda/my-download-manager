"""
High-Density Queue View Container for Smart Download Manager.
Handles category filtering, instant search filtering, multi-selection,
and high-density QueueRowCard layout.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set
import customtkinter as ctk

from queue_manager import QueueItem, QueueItemStatus
from ui.icons import get_icon
from ui.queue_card import QueueRowCard
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_DIM,
    COLOR_ACCENT,
    COLOR_SUCCESS,
    COLOR_WARNING,
    RADIUS_CARD,
    RADIUS_BUTTON,
    get_title_font,
    get_section_font,
    get_bold_font,
    get_body_font,
    get_caption_font,
)


class QueueView(ctk.CTkFrame):
    """Container for the High-Density Download Queue."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_add_click: Callable[[], None],
        on_pause_item: Callable[[str], None],
        on_resume_item: Callable[[str], None],
        on_refresh_item: Callable[[str], None],
        on_remove_item: Callable[[str], None],
        on_delete_disk: Callable[[str], None],
    ):
        super().__init__(parent, fg_color=COLOR_BG_WINDOW, corner_radius=0)
        self.on_add_click = on_add_click
        self.on_pause_item = on_pause_item
        self.on_resume_item = on_resume_item
        self.on_refresh_item = on_refresh_item
        self.on_remove_item = on_remove_item
        self.on_delete_disk = on_delete_disk

        self.cards: Dict[str, QueueRowCard] = {}
        self.selected_ids: Set[str] = set()
        self.active_category: str = "all"
        self.search_query: str = ""
        self.all_items: List[QueueItem] = []

        self._build_ui()

    def _build_ui(self) -> None:
        # Header bar
        self.header_bar = ctk.CTkFrame(self, height=38, fg_color="transparent")
        self.header_bar.pack(fill="x", padx=16, pady=(10, 6))
        self.header_bar.pack_propagate(False)

        self.filter_title = ctk.CTkLabel(
            self.header_bar,
            text="All Downloads",
            font=get_section_font(),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        self.filter_title.pack(side="left")

        self.stats_badge = ctk.CTkLabel(
            self.header_bar,
            text="",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
            anchor="e",
        )
        self.stats_badge.pack(side="right")

        # Scrollable container for cards
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        # Empty state container
        self.empty_state_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        self.empty_state_frame.pack(fill="both", expand=True, pady=60)

        empty_icon = ctk.CTkLabel(
            self.empty_state_frame,
            text="",
            image=get_icon("download", COLOR_TEXT_DIM, (42, 42)),
        )
        empty_icon.pack(pady=(0, 10))

        self.empty_lbl = ctk.CTkLabel(
            self.empty_state_frame,
            text="No downloads found in this view.\nClick '+ Add Download' or 'Batch Ingestion' to get started.",
            font=get_body_font(),
            text_color=COLOR_TEXT_MUTED,
            justify="center",
        )
        self.empty_lbl.pack(pady=(0, 14))

        add_prompt_btn = ctk.CTkButton(
            self.empty_state_frame,
            text=" Add Download",
            image=get_icon("plus", COLOR_TEXT_PRIMARY, (14, 14)),
            compound="left",
            width=140,
            height=32,
            corner_radius=RADIUS_BUTTON,
            fg_color=COLOR_ACCENT,
            command=self.on_add_click,
        )
        add_prompt_btn.pack()

    def set_category_filter(self, category: str) -> None:
        self.active_category = category
        cat_names = {
            "all": "All Downloads",
            "downloading": "Active Downloads",
            "paused": "Paused Downloads",
            "expired": "Expired / Action Required",
            "completed": "Completed Downloads",
            "http": "Direct Web (HTTP) Downloads",
            "torrents": "BitTorrent & Magnet Downloads",
        }
        self.filter_title.configure(text=cat_names.get(category, "Downloads"))
        self._refilter_cards()

    def set_search_query(self, query: str) -> None:
        self.search_query = query.lower().strip()
        self._refilter_cards()

    def update_items(self, items: List[QueueItem]) -> None:
        self.all_items = items
        current_ids = {it.id for it in items}

        # Remove cards that no longer exist
        for item_id in list(self.cards.keys()):
            if item_id not in current_ids:
                card = self.cards.pop(item_id)
                self.selected_ids.discard(item_id)
                card.destroy()

        # Update or create cards
        for it in items:
            if it.id in self.cards:
                self.cards[it.id].update_data(it)
            else:
                card = QueueRowCard(
                    self.scroll_frame,
                    it,
                    on_select=self._on_card_select,
                    on_pause=self.on_pause_item,
                    on_resume=self.on_resume_item,
                    on_refresh=self.on_refresh_item,
                    on_remove=self.on_remove_item,
                    on_delete_disk=self.on_delete_disk,
                )
                self.cards[it.id] = card

        self._refilter_cards()
        self._update_stats_badge()

    def _matches_filter(self, item: QueueItem) -> bool:
        # Search query match
        if self.search_query:
            if (
                self.search_query not in item.display_name.lower()
                and self.search_query not in item.url.lower()
            ):
                return False

        # Category match
        cat = self.active_category
        if cat == "all":
            return True
        elif cat == "downloading":
            return item.status == QueueItemStatus.ACTIVE
        elif cat == "paused":
            return item.status in (QueueItemStatus.PAUSED, QueueItemStatus.QUEUED)
        elif cat == "expired":
            return item.status == QueueItemStatus.EXPIRED
        elif cat == "completed":
            return item.status in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED)
        elif cat == "http":
            return not item.is_torrent_task
        elif cat == "torrents":
            return item.is_torrent_task
        return True

    def _refilter_cards(self) -> None:
        visible_count = 0
        for it in self.all_items:
            card = self.cards.get(it.id)
            if not card:
                continue

            matches = self._matches_filter(it)
            if matches:
                if not card.winfo_ismapped():
                    card.pack(fill="x", padx=4, pady=3)
                visible_count += 1
            else:
                if card.winfo_ismapped():
                    card.pack_forget()

        if visible_count == 0:
            if not self.empty_state_frame.winfo_ismapped():
                self.empty_state_frame.pack(fill="both", expand=True, pady=60)
        else:
            if self.empty_state_frame.winfo_ismapped():
                self.empty_state_frame.pack_forget()

    def _update_stats_badge(self) -> None:
        active_count = sum(1 for it in self.all_items if it.status == QueueItemStatus.ACTIVE)
        total_speed = sum(it.speed for it in self.all_items if it.status == QueueItemStatus.ACTIVE)
        if total_speed > 0:
            speed_txt = f"{total_speed / (1024 * 1024):.1f} MB/s" if total_speed >= 1024 * 1024 else f"{total_speed / 1024:.1f} KB/s"
            self.stats_badge.configure(text=f"{active_count} Active · {speed_txt}")
        else:
            self.stats_badge.configure(text=f"{len(self.all_items)} Items")

    def _on_card_select(self, item_id: str, multi: bool) -> None:
        if not multi:
            for i_id, card in self.cards.items():
                if i_id != item_id:
                    card.set_selected(False)
            self.selected_ids.clear()

        if item_id in self.selected_ids:
            self.selected_ids.remove(item_id)
            self.cards[item_id].set_selected(False)
        else:
            self.selected_ids.add(item_id)
            if item_id in self.cards:
                self.cards[item_id].set_selected(True)

    def select_all(self) -> None:
        for it in self.all_items:
            if self._matches_filter(it):
                self.selected_ids.add(it.id)
                if it.id in self.cards:
                    self.cards[it.id].set_selected(True)

    def clear_selection(self) -> None:
        for i_id in list(self.selected_ids):
            if i_id in self.cards:
                self.cards[i_id].set_selected(False)
        self.selected_ids.clear()

    def get_selected_ids(self) -> List[str]:
        return list(self.selected_ids)
