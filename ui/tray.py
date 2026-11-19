"""
Windows System Tray Integration for Smart Download Manager.
Implements background persistence, status telemetry, and right-click tray actions
using native Windows Win32 Shell_NotifyIcon without heavy external dependencies.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

WM_TRAY_MSG = 0x8000 + 20  # WM_USER + 20

ID_RESTORE = 1001
ID_PAUSE_ALL = 1002
ID_RESUME_ALL = 1003
ID_BRIDGE_INFO = 1004
ID_EXIT = 1005


class WindowsSystemTray:
    """Thread-safe Windows system tray icon manager."""

    def __init__(
        self,
        icon_path: Optional[str] = None,
        tooltip: str = "Smart Download Manager",
        on_restore: Optional[Callable[[], None]] = None,
        on_pause_all: Optional[Callable[[], None]] = None,
        on_resume_all: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        get_bridge_status: Optional[Callable[[], str]] = None,
    ):
        self.icon_path = icon_path or str(Path.cwd() / "app_icon.ico")
        self.tooltip = tooltip
        self.on_restore = on_restore
        self.on_pause_all = on_pause_all
        self.on_resume_all = on_resume_all
        self.on_exit = on_exit
        self.get_bridge_status = get_bridge_status

        self.hwnd = None
        self._thread: Optional[threading.Thread] = None
        self._is_active = False
        self._is_downloading = False
        self._hicon = None

    def start(self) -> None:
        """Start system tray in a background thread with Windows message loop."""
        if sys.platform != "win32":
            return
        if self._is_active:
            return

        self._thread = threading.Thread(target=self._run_tray_loop, name="SystemTrayThread", daemon=True)
        self._thread.start()

    def _run_tray_loop(self) -> None:
        try:
            import win32gui
            import win32con
        except ImportError:
            log.warning("win32gui not available. System tray disabled.")
            return

        wc = win32gui.WNDCLASS()
        hinst = win32gui.GetModuleHandle(None)
        wc.hInstance = hinst
        wc.lpszClassName = f"SmartDownloadManagerTray_{os.getpid()}"
        wc.lpfnWndProc = self._wnd_proc

        try:
            class_atom = win32gui.RegisterClass(wc)
        except Exception:
            class_atom = None

        self.hwnd = win32gui.CreateWindow(
            wc.lpszClassName,
            "SmartDownloadManagerTrayWindow",
            0,
            0,
            0,
            win32con.CW_USEDEFAULT,
            win32con.CW_USEDEFAULT,
            0,
            0,
            hinst,
            None,
        )
        win32gui.UpdateWindow(self.hwnd)

        # Load icon
        if os.path.exists(self.icon_path):
            try:
                self._hicon = win32gui.LoadImage(
                    0,
                    os.path.abspath(self.icon_path),
                    win32con.IMAGE_ICON,
                    16,
                    16,
                    win32con.LR_LOADFROMFILE,
                )
            except Exception:
                self._hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        else:
            self._hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (self.hwnd, 0, flags, WM_TRAY_MSG, self._hicon, self.tooltip)
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
            self._is_active = True
        except Exception as exc:
            log.debug(f"Shell_NotifyIcon NIM_ADD not available in this environment: {exc}")
            self._is_active = False

        try:
            win32gui.PumpMessages()
        except Exception:
            pass

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        import win32gui
        import win32con

        if msg == WM_TRAY_MSG:
            if lparam in (win32con.WM_LBUTTONDBLCLK, win32con.WM_LBUTTONUP):
                if self.on_restore:
                    self.on_restore()
                return 0

            elif lparam == win32con.WM_RBUTTONUP:
                self._show_context_menu(hwnd)
                return 0

        elif msg == win32con.WM_COMMAND:
            cmd_id = wparam & 0xFFFF
            if cmd_id == ID_RESTORE:
                if self.on_restore:
                    self.on_restore()
            elif cmd_id == ID_PAUSE_ALL:
                if self.on_pause_all:
                    self.on_pause_all()
            elif cmd_id == ID_RESUME_ALL:
                if self.on_resume_all:
                    self.on_resume_all()
            elif cmd_id == ID_EXIT:
                if self.on_exit:
                    self.on_exit()
            return 0

        elif msg == win32con.WM_DESTROY:
            nid = (hwnd, 0)
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_context_menu(self, hwnd) -> None:
        import win32gui
        import win32con

        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_RESTORE, "Open Smart Download Manager")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_PAUSE_ALL, "Pause All Downloads")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_RESUME_ALL, "Resume All Downloads")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        bridge_text = "Extension Bridge: Active (Port 8992)"
        if self.get_bridge_status:
            bridge_text = self.get_bridge_status()
        win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, ID_BRIDGE_INFO, bridge_text)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_EXIT, "Exit Completely")

        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(hwnd)
        win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
            pos[0],
            pos[1],
            0,
            hwnd,
            None,
        )
        win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)

    def update_tooltip(self, text: str) -> None:
        """Update system tray hover tooltip."""
        if not self._is_active or not self.hwnd:
            return
        try:
            import win32gui
            nid = (self.hwnd, 0, win32gui.NIF_TIP, WM_TRAY_MSG, self._hicon, text[:127])
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)
        except Exception:
            pass

    def stop(self) -> None:
        """Remove icon from notification area and terminate tray message loop."""
        if not self._is_active or not self.hwnd:
            return
        try:
            import win32gui
            import win32con
            nid = (self.hwnd, 0)
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        self._is_active = False
