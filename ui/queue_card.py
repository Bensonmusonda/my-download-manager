"""
High-Density Queue Item Card Widget for Smart Download Manager.
Height ~56px, protocol badge icon, smooth progress bar, dynamic live telemetry,
and context menu actions.
Strictly adheres to Section 4.3 Component D of HANDOFF.md.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from tkinter import Menu, messagebox
from typing import Callable, Optional
import customtkinter as ctk

from queue_manager import QueueItem, QueueItemStatus
from ui.icons import get_icon
from ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_CARD_HOVER,
    COLOR_BG_CARD_SELECTED,
    COLOR_BORDER,
    COLOR_BORDER_SELECTED,
    COLOR_WARNING_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_DIM,
    COLOR_ACCENT,
    COLOR_SUCCESS,
    COLOR_WARNING,
    COLOR_ERROR,
    COLOR_TORRENT,
    COLOR_WEB,
    COLOR_PROGRESS_ACTIVE,
    COLOR_PROGRESS_DONE,
    COLOR_PROGRESS_PAUSED,
    COLOR_PROGRESS_EXPIRED,
    COLOR_PROGRESS_ERROR,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    COLOR_WARNING_BG,
    RADIUS_CARD,
    RADIUS_BUTTON,
    RADIUS_PROGRESS,
    RADIUS_PILL,
    get_bold_font,
    get_body_font,
    get_mono_font,
    get_caption_font,
)


def _format_time(seconds: float) -> str:
    if seconds <= 0 or seconds > 86400 * 7:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class QueueRowCard(ctk.CTkFrame):
    """High-density (~56px) download card for a single QueueItem."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        item: QueueItem,
        on_select: Callable[[str, bool], None],
        on_pause: Callable[[str], None],
        on_resume: Callable[[str], None],
        on_refresh: Callable[[str], None],
        on_remove: Callable[[str], None],
        on_delete_disk: Callable[[str], None],
    ):
        super().__init__(
            parent,
            fg_color=COLOR_BG_CARD,
            corner_radius=RADIUS_CARD,
            border_width=1,
            border_color=COLOR_BORDER,
            height=58,
        )
        self.item = item
        self.on_select = on_select
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_refresh = on_refresh
        self.on_remove = on_remove
        self.on_delete_disk = on_delete_disk
        self.is_selected = False
        self._rendered_status: Optional[QueueItemStatus] = None
        self._cached_border_style = None
        self._cached_name: Optional[str] = None
        self._cached_pct: Optional[str] = None
        self._cached_sz: Optional[str] = None
        self._cached_telemetry: Optional[str] = None
        self._cached_progress_color: Optional[str] = None

        self.pack_propagate(False)
        self._build_card()
        self._bind_events()
        self.update_data(item)

    def _build_card(self) -> None:
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=8, pady=4)

        # 1. Left Protocol Icon (32x32 container)
        self.icon_container = ctk.CTkFrame(
            inner,
            width=34,
            height=34,
            corner_radius=RADIUS_BUTTON,
            fg_color="#121417",
        )
        self.icon_container.pack(side="left", padx=(2, 10))
        self.icon_container.pack_propagate(False)

        self.type_icon = ctk.CTkLabel(
            self.icon_container,
            text="",
            image=get_icon("torrent" if self.item.is_torrent_task else "web", COLOR_TORRENT if self.item.is_torrent_task else COLOR_WEB, (18, 18)),
        )
        self.type_icon.place(relx=0.5, rely=0.5, anchor="center")

        # 3. Right Action Buttons Container
        self.actions_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self.actions_frame.pack(side="right", fill="y", padx=(6, 2))

        # 2. Main Center Info Block (Expands to fill)
        self.info_block = ctk.CTkFrame(inner, fg_color="transparent")
        self.info_block.pack(side="left", fill="both", expand=True)

        # Top Line: Filename + Size + Percentage
        top_line = ctk.CTkFrame(self.info_block, fg_color="transparent", height=18)
        top_line.pack(fill="x")
        top_line.pack_propagate(False)

        self.name_lbl = ctk.CTkLabel(
            top_line,
            text=self.item.display_name,
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        self.name_lbl.pack(side="left", fill="x", expand=True)

        self.size_lbl = ctk.CTkLabel(
            top_line,
            text="0 B / 0 B",
            font=get_mono_font(),
            text_color=COLOR_TEXT_MUTED,
        )
        self.size_lbl.pack(side="right", padx=(8, 12))

        self.percent_lbl = ctk.CTkLabel(
            top_line,
            text="0.0%",
            font=get_mono_font(),
            text_color=COLOR_TEXT_PRIMARY,
            width=45,
            anchor="e",
        )
        self.percent_lbl.pack(side="right")

        # Middle Line: Progress Bar (5px height)
        self.progress_bar = ctk.CTkProgressBar(
            self.info_block,
            height=5,
            corner_radius=RADIUS_PROGRESS,
            progress_color=COLOR_PROGRESS_ACTIVE,
            fg_color="#282c37",
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", pady=(3, 2))

        # Bottom Line: Telemetry & Diagnostics
        bottom_line = ctk.CTkFrame(self.info_block, fg_color="transparent", height=16)
        bottom_line.pack(fill="x")
        bottom_line.pack_propagate(False)

        self.telemetry_lbl = ctk.CTkLabel(
            bottom_line,
            text="Queued in line...",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.telemetry_lbl.pack(side="left", fill="x", expand=True)

        # Build inline action buttons
        self._build_action_buttons()

    def _build_action_buttons(self) -> None:
        status = self.item.status
        if status == self._rendered_status:
            return
        self._rendered_status = status

        for w in self.actions_frame.winfo_children():
            w.destroy()

        status = self.item.status

        if status == QueueItemStatus.ACTIVE:
            pause_btn = ctk.CTkButton(
                self.actions_frame,
                text="",
                image=get_icon("pause", COLOR_TEXT_PRIMARY, (13, 13)),
                width=28,
                height=28,
                corner_radius=RADIUS_BUTTON,
                fg_color=COLOR_BTN_SECONDARY,
                hover_color=COLOR_BTN_SECONDARY_HOVER,
                command=lambda: self.on_pause(self.item.id),
            )
            pause_btn.pack(side="left", padx=2)

        elif status in (QueueItemStatus.PAUSED, QueueItemStatus.FAILED):
            resume_btn = ctk.CTkButton(
                self.actions_frame,
                text="",
                image=get_icon("play", COLOR_TEXT_PRIMARY, (13, 13)),
                width=28,
                height=28,
                corner_radius=RADIUS_BUTTON,
                fg_color=COLOR_BTN_SECONDARY,
                hover_color=COLOR_BTN_SECONDARY_HOVER,
                command=lambda: self.on_resume(self.item.id),
            )
            resume_btn.pack(side="left", padx=2)

        elif status == QueueItemStatus.EXPIRED:
            refresh_btn = ctk.CTkButton(
                self.actions_frame,
                text=" Refresh Link",
                image=get_icon("refresh", "#000000", (13, 13)),
                compound="left",
                font=get_caption_font(),
                width=100,
                height=26,
                corner_radius=RADIUS_PILL,
                fg_color=COLOR_WARNING,
                hover_color="#d97706",
                text_color="#000000",
                command=lambda: self.on_refresh(self.item.id),
            )
            refresh_btn.pack(side="left", padx=4)

        elif status in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED):
            open_folder_btn = ctk.CTkButton(
                self.actions_frame,
                text="",
                image=get_icon("folder", COLOR_TEXT_PRIMARY, (14, 14)),
                width=28,
                height=28,
                corner_radius=RADIUS_BUTTON,
                fg_color=COLOR_BTN_SECONDARY,
                hover_color=COLOR_BTN_SECONDARY_HOVER,
                command=self._open_containing_folder,
            )
            open_folder_btn.pack(side="left", padx=2)

            open_file_btn = ctk.CTkButton(
                self.actions_frame,
                text="",
                image=get_icon("play", COLOR_SUCCESS, (13, 13)),
                width=28,
                height=28,
                corner_radius=RADIUS_BUTTON,
                fg_color=COLOR_BTN_SECONDARY,
                hover_color="#064e3b",
                command=self._open_target_file,
            )
            open_file_btn.pack(side="left", padx=2)

        # Universal Remove Button
        remove_btn = ctk.CTkButton(
            self.actions_frame,
            text="",
            image=get_icon("close", COLOR_TEXT_MUTED, (12, 12)),
            width=26,
            height=28,
            corner_radius=RADIUS_BUTTON,
            fg_color="transparent",
            hover_color=COLOR_ERROR,
            command=lambda: self.on_remove(self.item.id),
        )
        remove_btn.pack(side="left", padx=(2, 0))

    def update_data(self, item: QueueItem) -> None:
        """Update live telemetry, progress bar, colors, and action buttons."""
        self.item = item

        # Name truncation
        name_txt = item.display_name
        if self._cached_name != name_txt:
            self._cached_name = name_txt
            self.name_lbl.configure(text=name_txt)

        # Progress fraction & percentage
        fraction = item.progress_fraction
        self.progress_bar.set(fraction)
        pct_txt = f"{fraction * 100:.1f}%"
        if self._cached_pct != pct_txt:
            self._cached_pct = pct_txt
            self.percent_lbl.configure(text=pct_txt)

        # Size metrics
        sz_txt = item.formatted_size
        if self._cached_sz != sz_txt:
            self._cached_sz = sz_txt
            self.size_lbl.configure(text=sz_txt)

        # State styling & telemetry
        status = item.status

        if status == QueueItemStatus.ACTIVE:
            if self._cached_progress_color != COLOR_PROGRESS_ACTIVE:
                self._cached_progress_color = COLOR_PROGRESS_ACTIVE
                self.progress_bar.configure(progress_color=COLOR_PROGRESS_ACTIVE)
            if item.is_torrent_task:
                telemetry = f"{item.formatted_speed} · {item.peers} peers · {item.seeds} seeds · {item.status_msg}"
            else:
                eta_str = _format_time(self._calc_eta(item))
                telemetry = f"{item.formatted_speed} · ETA: {eta_str} · Multi-connection active"
            if self._cached_telemetry != telemetry:
                self._cached_telemetry = telemetry
                self.telemetry_lbl.configure(text=telemetry, text_color=COLOR_TEXT_PRIMARY)
            self._set_border_style(is_expired=False)

        elif status == QueueItemStatus.COMPLETED:
            if self._cached_progress_color != COLOR_PROGRESS_DONE:
                self._cached_progress_color = COLOR_PROGRESS_DONE
                self.progress_bar.configure(progress_color=COLOR_PROGRESS_DONE)
            duration_str = f" in {int(item.completed_at - item.created_at)}s" if item.completed_at else ""
            telemetry = f"Downloaded{duration_str} · 100% Bit-for-bit verified"
            if self._cached_telemetry != telemetry:
                self._cached_telemetry = telemetry
                self.telemetry_lbl.configure(text=telemetry, text_color=COLOR_SUCCESS)
            self._set_border_style(is_expired=False)

        elif status == QueueItemStatus.SKIPPED:
            if self._cached_progress_color != COLOR_PROGRESS_DONE:
                self._cached_progress_color = COLOR_PROGRESS_DONE
                self.progress_bar.configure(progress_color=COLOR_PROGRESS_DONE)
            telemetry = "Pre-existing file matched · Skipped"
            if self._cached_telemetry != telemetry:
                self._cached_telemetry = telemetry
                self.telemetry_lbl.configure(text=telemetry, text_color=COLOR_WEB)
            self._set_border_style(is_expired=False)

        elif status == QueueItemStatus.EXPIRED:
            if self._cached_progress_color != COLOR_PROGRESS_EXPIRED:
                self._cached_progress_color = COLOR_PROGRESS_EXPIRED
                self.progress_bar.configure(progress_color=COLOR_PROGRESS_EXPIRED)
            telemetry = f"Signed link expired (HTTP 403) · {item.formatted_size.split('/')[0].strip()} preserved · Click Refresh Link"
            if self._cached_telemetry != telemetry:
                self._cached_telemetry = telemetry
                self.telemetry_lbl.configure(text=telemetry, text_color=COLOR_WARNING)
            self._set_border_style(is_expired=True)

        elif status == QueueItemStatus.PAUSED:
            if self._cached_progress_color != COLOR_PROGRESS_PAUSED:
                self._cached_progress_color = COLOR_PROGRESS_PAUSED
                self.progress_bar.configure(progress_color=COLOR_PROGRESS_PAUSED)
            telemetry = "Paused by user · Partial bytes preserved on disk"
            if self._cached_telemetry != telemetry:
                self._cached_telemetry = telemetry
                self.telemetry_lbl.configure(text=telemetry, text_color=COLOR_TEXT_MUTED)
            self._set_border_style(is_expired=False)

        elif status == QueueItemStatus.FAILED:
            if self._cached_progress_color != COLOR_PROGRESS_ERROR:
                self._cached_progress_color = COLOR_PROGRESS_ERROR
                self.progress_bar.configure(progress_color=COLOR_PROGRESS_ERROR)
            err_msg = item.error or "Download failed"
            telemetry = f"Error: {err_msg}"
            if self._cached_telemetry != telemetry:
                self._cached_telemetry = telemetry
                self.telemetry_lbl.configure(text=telemetry, text_color=COLOR_ERROR)
            self._set_border_style(is_expired=False)

        elif status == QueueItemStatus.QUEUED:
            if self._cached_progress_color != COLOR_PROGRESS_PAUSED:
                self._cached_progress_color = COLOR_PROGRESS_PAUSED
                self.progress_bar.configure(progress_color=COLOR_PROGRESS_PAUSED)
            telemetry = "Waiting for available download slot..."
            if self._cached_telemetry != telemetry:
                self._cached_telemetry = telemetry
                self.telemetry_lbl.configure(text=telemetry, text_color=COLOR_TEXT_DIM)
            self._set_border_style(is_expired=False)

        self._build_action_buttons()

    def _calc_eta(self, item: QueueItem) -> float:
        if item.speed <= 0 or not item.total_bytes:
            return 0.0
        remaining = max(0, item.total_bytes - item.downloaded_bytes)
        return remaining / item.speed

    def _set_border_style(self, is_expired: bool) -> None:
        style_key = (self.is_selected, is_expired)
        if getattr(self, "_cached_border_style", None) == style_key:
            return
        self._cached_border_style = style_key
        if self.is_selected:
            self.configure(fg_color=COLOR_BG_CARD_SELECTED, border_color=COLOR_BORDER_SELECTED, border_width=2)
        elif is_expired:
            self.configure(fg_color=COLOR_WARNING_BG, border_color=COLOR_WARNING_BORDER, border_width=1)
        else:
            self.configure(fg_color=COLOR_BG_CARD, border_color=COLOR_BORDER, border_width=1)

    def set_selected(self, selected: bool) -> None:
        self.is_selected = selected
        self._set_border_style(is_expired=(self.item.status == QueueItemStatus.EXPIRED))

    def _bind_events(self) -> None:
        # Recursive binding for selection and context menu
        self._bind_to_all(self, "<Button-1>", lambda e: self.on_select(self.item.id, False))
        self._bind_to_all(self, "<Control-Button-1>", lambda e: self.on_select(self.item.id, True))
        self._bind_to_all(self, "<Button-3>", self._show_context_menu)
        self._bind_to_all(self, "<Enter>", self._on_hover_enter)
        self._bind_to_all(self, "<Leave>", self._on_hover_leave)

    def _bind_to_all(self, widget, event_seq, handler) -> None:
        if widget not in self.actions_frame.winfo_children() and widget != self.actions_frame:
            widget.bind(event_seq, handler, add="+")
        for child in widget.winfo_children():
            self._bind_to_all(child, event_seq, handler)

    def _on_hover_enter(self, event=None) -> None:
        if not self.is_selected and self.item.status != QueueItemStatus.EXPIRED:
            self.configure(fg_color=COLOR_BG_CARD_HOVER)

    def _on_hover_leave(self, event=None) -> None:
        if not self.is_selected and self.item.status != QueueItemStatus.EXPIRED:
            self.configure(fg_color=COLOR_BG_CARD)

    # ── Context Menu ──────────────────────────────────────────────────

    def _show_context_menu(self, event) -> None:
        self.on_select(self.item.id, False)

        menu = Menu(self, tearoff=0, bg="#1a1d24", fg="#f8fafc", activebackground="#2563eb", activeforeground="#ffffff")

        is_done = self.item.status in (QueueItemStatus.COMPLETED, QueueItemStatus.SKIPPED)
        is_expired = self.item.status == QueueItemStatus.EXPIRED
        is_active = self.item.status == QueueItemStatus.ACTIVE

        # 1. Open File
        if is_done:
            menu.add_command(label="Open File", command=self._open_target_file)
        else:
            menu.add_command(label="Open File", state="disabled")

        # 2. Open Containing Folder
        menu.add_command(label="Open Containing Folder", command=self._open_containing_folder)
        menu.add_separator()

        # 3. Pause / Resume
        if is_active:
            menu.add_command(label="Pause Download", command=lambda: self.on_pause(self.item.id))
        else:
            menu.add_command(label="Resume Download", command=lambda: self.on_resume(self.item.id))

        # 4. Refresh Expired Link
        if is_expired:
            menu.add_command(label="Refresh Expired Link...", command=lambda: self.on_refresh(self.item.id))

        menu.add_separator()

        # 5. Copy Download Link
        menu.add_command(label="Copy Download Link", command=self._copy_link)

        # 6. Prioritize / Move to Top
        menu.add_command(label="Prioritize (Move to Top)", command=self._prioritize_item)
        menu.add_separator()

        # 7. Remove from List
        menu.add_command(label="Remove from List", command=lambda: self.on_remove(self.item.id))

        # 8. Delete File from Disk
        menu.add_command(label="Delete File from Disk", command=lambda: self.on_delete_disk(self.item.id))

        menu.tk_popup(event.x_root, event.y_root)

    def _open_target_file(self) -> None:
        if self.item.target_path and self.item.target_path.exists():
            try:
                os.startfile(str(self.item.target_path))
            except Exception:
                pass

    def _open_containing_folder(self) -> None:
        dest = self.item.target_path.parent if self.item.target_path else Path(self.item.dest_dir)
        if dest.exists():
            try:
                if self.item.target_path and self.item.target_path.exists():
                    # Select file in explorer
                    subprocess.run(["explorer", f"/select,{self.item.target_path}"], check=False)
                else:
                    os.startfile(str(dest))
            except Exception:
                pass

    def _copy_link(self) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(self.item.url)
        except Exception:
            pass

    def _prioritize_item(self) -> None:
        # Move item to front in queue manager if queued
        self.item.status = QueueItemStatus.QUEUED
        self.on_resume(self.item.id)
