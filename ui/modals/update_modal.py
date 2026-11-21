"""
Software Update Dialog for Smart Download Manager.
Displays release information, changelog, live download progress, and executes in-app update with auto-restart.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Callable, Optional

import customtkinter as ctk

from ui.icons import get_icon
from ui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_HOVER,
    COLOR_BG_CARD,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    RADIUS_BUTTON,
    RADIUS_CARD,
    get_body_font,
    get_bold_font,
    get_caption_font,
    get_title_font,
)
from updater import CURRENT_VERSION, ReleaseAsset, UpdateChecker, UpdateInfo

log = logging.getLogger(__name__)


def _format_bytes(b: int) -> str:
    if b <= 0:
        return "Unknown size"
    elif b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    else:
        return f"{b / (1024 * 1024 * 1024):.2f} GB"


class UpdateModal(ctk.CTkToplevel):
    """
    Modal dialog displaying available update details, changelog,
    and a one-click 'Update & Restart' action.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        update_info: UpdateInfo,
        before_restart_cb: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.info = update_info
        self.before_restart_cb = before_restart_cb
        self.preferred_asset: Optional[ReleaseAsset] = update_info.get_preferred_asset()

        self._is_updating = False

        self.title("Software Update Available")
        self.geometry("640x560")
        self.minsize(580, 480)
        self.transient(parent)
        self.configure(fg_color=COLOR_BG_WINDOW)

        self._build_ui()
        self.bind("<Escape>", lambda e: self._on_cancel())
        self._center_window()

    def _center_window(self) -> None:
        self.update_idletasks()
        try:
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            px = self.parent.winfo_x()
            py = self.parent.winfo_y()
            w, h = 640, 560
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # ── Header ──────────────────────────────────────────────────────────
        header = ctk.CTkFrame(container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        icon_lbl = ctk.CTkLabel(
            header,
            text="",
            image=get_icon("refresh", COLOR_ACCENT, (28, 28)),
        )
        icon_lbl.pack(side="left", padx=(0, 12))

        header_text = ctk.CTkFrame(header, fg_color="transparent")
        header_text.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            header_text,
            text=f"New Version Available: v{self.info.remote_version}",
            font=get_title_font(),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")

        date_str = f" · Released {self.info.published_at[:10]}" if self.info.published_at else ""
        ctk.CTkLabel(
            header_text,
            text=f"Current: v{CURRENT_VERSION}  →  New: v{self.info.remote_version}{date_str}",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w")

        # ── Release Notes Box ───────────────────────────────────────────────
        notes_frame = ctk.CTkFrame(
            container,
            fg_color=COLOR_BG_CARD,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=RADIUS_CARD,
        )
        notes_frame.pack(fill="both", expand=True, pady=(0, 14))

        notes_header = ctk.CTkFrame(notes_frame, fg_color="transparent")
        notes_header.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            notes_header,
            text="What's New in this Release:",
            font=get_bold_font(),
            text_color=COLOR_TEXT_PRIMARY,
        ).pack(side="left")

        if self.preferred_asset:
            asset_info_text = f"Package: {self.preferred_asset.name} ({_format_bytes(self.preferred_asset.size)})"
            ctk.CTkLabel(
                notes_header,
                text=asset_info_text,
                font=get_caption_font(),
                text_color=COLOR_ACCENT,
            ).pack(side="right")

        self.textbox = ctk.CTkTextbox(
            notes_frame,
            fg_color="transparent",
            text_color=COLOR_TEXT_PRIMARY,
            font=get_body_font(),
            wrap="word",
        )
        self.textbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Insert release notes
        notes_body = (self.info.release_notes or "No release notes provided for this version.").strip()
        self.textbox.insert("1.0", notes_body)
        self.textbox.configure(state="disabled")

        # ── Progress & Status Section ───────────────────────────────────────
        self.progress_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.progress_frame.pack(fill="x", pady=(0, 14))

        self.status_lbl = ctk.CTkLabel(
            self.progress_frame,
            text="Click 'Update & Restart' to automatically download and apply the update.",
            font=get_caption_font(),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.status_lbl.pack(fill="x", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            height=8,
            corner_radius=4,
            progress_color=COLOR_ACCENT,
            fg_color=COLOR_BG_CARD,
        )
        self.progress_bar.set(0.0)

        # ── Action Buttons Footer ───────────────────────────────────────────
        btn_bar = ctk.CTkFrame(container, fg_color="transparent")
        btn_bar.pack(fill="x")

        # Left: View on GitHub
        self.btn_github = ctk.CTkButton(
            btn_bar,
            text="  🌐  View on GitHub",
            font=get_caption_font(),
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            corner_radius=RADIUS_BUTTON,
            height=32,
            command=self._open_github,
        )
        self.btn_github.pack(side="left")

        # Right: Later (Cancel)
        self.btn_later = ctk.CTkButton(
            btn_bar,
            text="Later",
            font=get_caption_font(),
            fg_color="transparent",
            hover_color=COLOR_BTN_SECONDARY,
            text_color=COLOR_TEXT_MUTED,
            corner_radius=RADIUS_BUTTON,
            height=32,
            width=80,
            command=self._on_cancel,
        )
        self.btn_later.pack(side="right", padx=(8, 0))

        # Right: Update & Restart (Primary Action)
        self.btn_update = ctk.CTkButton(
            btn_bar,
            text="  ⚡  Update & Restart",
            font=get_bold_font(),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            corner_radius=RADIUS_BUTTON,
            height=32,
            command=self._start_update,
        )
        self.btn_update.pack(side="right")

    def _open_github(self) -> None:
        target_url = self.info.html_url or f"https://github.com/Bensonmusonda/my-download-manager/releases/tag/{self.info.tag_name}"
        webbrowser.open(target_url)

    def _on_cancel(self) -> None:
        if self._is_updating:
            return  # Prevent closing while actively applying update
        self.destroy()

    def _start_update(self) -> None:
        if self._is_updating:
            return
        if not self.preferred_asset:
            self.status_lbl.configure(
                text="⚠ No matching binary asset found for your platform. Opening GitHub release page...",
                text_color=COLOR_ERROR,
            )
            self._open_github()
            return

        self._is_updating = True
        self.btn_update.configure(state="disabled", text="Updating...")
        self.btn_later.configure(state="disabled")
        self.progress_bar.pack(fill="x", pady=(0, 2))
        self.progress_bar.set(0.0)
        self.status_lbl.configure(
            text=f"Connecting to download {self.preferred_asset.name}...",
            text_color=COLOR_ACCENT,
        )

        threading.Thread(target=self._run_update_worker, daemon=True).start()

    def _run_update_worker(self) -> None:
        asset = self.preferred_asset
        if not asset:
            return

        def _progress_cb(frac: float, downloaded: int, total: int) -> None:
            self.after(0, lambda: self._update_progress_ui(frac, downloaded, total))

        success = UpdateChecker.download_and_apply_update(
            download_url=asset.download_url,
            progress_cb=_progress_cb,
            asset_name=asset.name,
            before_restart_cb=self.before_restart_cb,
        )

        if not success:
            self.after(0, self._on_update_failed)

    def _update_progress_ui(self, frac: float, downloaded: int, total: int) -> None:
        try:
            self.progress_bar.set(frac)
            pct = int(frac * 100)
            if total > 0:
                dl_str = _format_bytes(downloaded)
                tot_str = _format_bytes(total)
                self.status_lbl.configure(
                    text=f"Downloading update: {pct}% ({dl_str} of {tot_str})...",
                    text_color=COLOR_ACCENT,
                )
            else:
                self.status_lbl.configure(
                    text=f"Downloading update: {pct}%...",
                    text_color=COLOR_ACCENT,
                )

            if frac >= 1.0:
                self.status_lbl.configure(
                    text="Download complete! Applying update and restarting Smart Download Manager...",
                    text_color=COLOR_SUCCESS,
                )
        except Exception:
            pass

    def _on_update_failed(self) -> None:
        self._is_updating = False
        try:
            self.btn_update.configure(state="normal", text="  ⚡  Retry Update")
            self.btn_later.configure(state="normal")
            self.status_lbl.configure(
                text="❌ Update failed to download or execute. You can download manually via GitHub.",
                text_color=COLOR_ERROR,
            )
        except Exception:
            pass
