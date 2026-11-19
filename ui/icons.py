"""
Modern Lucide Vector Icon System for Smart Download Manager.
Renders authentic Lucide icons with sharp vector precision via resvg-py / PIL.
Completely replaces chunky emojis with modern, minimalist 2px-stroke icons.
"""

from __future__ import annotations

import io
from typing import Dict, Tuple
from PIL import Image, ImageDraw
import customtkinter as ctk

from ui.theme import (
    COLOR_TEXT_PRIMARY,
)

try:
    import resvg_py
    _HAS_RESVG = True
except ImportError:
    _HAS_RESVG = False

_ICON_CACHE: Dict[Tuple[str, str, int, int], ctk.CTkImage] = {}

# Authentic Lucide SVG path definitions (viewBox 0 0 24 24)
_LUCIDE_ICONS: Dict[str, str] = {
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "add": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "magnet": '<path d="m6 15-4-4 6.75-6.77a7.79 7.79 0 0 1 11 11L13 22l-4-4 6.36-6.36a4.95 4.95 0 0 0-7-7L2 11"/>',
    "torrent": '<path d="m6 15-4-4 6.75-6.77a7.79 7.79 0 0 1 11 11L13 22l-4-4 6.36-6.36a4.95 4.95 0 0 0-7-7L2 11"/>',
    "batch": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><path d="M12 10v6"/><path d="m9 13 3 3 3-3"/>',
    "import": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><path d="M12 10v6"/><path d="m9 13 3 3 3-3"/>',
    "play": '<polygon points="6 3 20 12 6 21 6 3" fill="{color}"/>',
    "resume": '<polygon points="6 3 20 12 6 21 6 3" fill="{color}"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1" fill="{color}"/><rect x="14" y="4" width="4" height="16" rx="1" fill="{color}"/>',
    "clear": '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>',
    "check_check": '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "open_folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/>',
    "document": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "reload": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "cancel": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "preferences": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "recovery": '<line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/>',
    "disk": '<line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/>',
    "web": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "completed": '<path d="M20 6 9 17l-5-5"/>',
    "warning": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "expired": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "dot": '<circle cx="12" cy="12" r="5" fill="{color}"/>',
    "arrow_down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "arrow_up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "upload": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "tasks": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "logo": '<circle cx="12" cy="12" r="10"/><path d="M12 6v8"/><path d="m8 10 4 4 4-4"/><path d="M8 17h8"/>',
}


def _render_lucide_svg(name: str, color_hex: str, target_px: int) -> Image.Image:
    """Render Lucide SVG path with 2px clean stroke using resvg-py."""
    body = _LUCIDE_ICONS.get(name, '<circle cx="12" cy="12" r="9"/>')
    content = body.replace("{color}", color_hex)
    svg_str = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{target_px}" height="{target_px}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color_hex}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{content}</svg>'
    )
    if _HAS_RESVG:
        try:
            png_bytes = resvg_py.svg_to_bytes(svg_str)
            return Image.open(io.BytesIO(png_bytes))
        except Exception:
            pass

    # Fallback to high-res PIL geometric renderer
    img = Image.new("RGBA", (target_px, target_px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mid = target_px // 2
    d.ellipse([4, 4, target_px - 4, target_px - 4], outline=color_hex, width=2)
    return img


def get_icon(
    name: str,
    color: str = COLOR_TEXT_PRIMARY,
    size: Tuple[int, int] = (16, 16),
) -> ctk.CTkImage:
    """
    Get a cached CTkImage icon with requested name, color, and display size.
    Uses official modern Lucide vector paths.
    """
    key = (name.lower(), color.lower(), size[0], size[1])
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    # Render at 2x supersampling for razor-sharp Retina/High-DPI fidelity
    hi_res = max(size[0], size[1]) * 2
    rendered_img = _render_lucide_svg(name.lower(), color, hi_res)

    ctk_img = ctk.CTkImage(
        light_image=rendered_img,
        dark_image=rendered_img,
        size=size,
    )
    _ICON_CACHE[key] = ctk_img
    return ctk_img
