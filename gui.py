"""
Smart Download Manager — gui.py

Modern desktop GUI built with CustomTkinter following Phase 6 UI/UX Modernization.
Features:
  • Modern Sidebar + Top Toolbar + High-Density Queue View + Status Bar shell
  • Category navigation and live item count badges
  • Smart 'New Download' modal with clipboard auto-inspection and collapsible options
  • Item-specific inline 403 link refresh dialog
  • Windows System Tray minimization and background persistence
  • Right-click context menus and desktop keyboard shortcuts
  • High-performance BitTorrent, Cloudflare-ready TLS, and Chrome Extension Bridge
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ui.app_window import SmartDownloaderApp, DEFAULT_DOWNLOAD_DIR

log = logging.getLogger(__name__)


def run_gui(
    default_dest: str = DEFAULT_DOWNLOAD_DIR,
    initial_batch_file: Optional[str] = None,
) -> None:
    """Launch the modernized CustomTkinter GUI mainloop."""
    app = SmartDownloaderApp(default_dest=default_dest, initial_batch_file=initial_batch_file)
    app.mainloop()


if __name__ == "__main__":
    run_gui()
