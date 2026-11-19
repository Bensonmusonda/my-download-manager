"""
Design System, Visual Tokens, and Styling Constants for Smart Download Manager.
Modern Dark Gray theme with refined contrast and bold typography.
"""

from __future__ import annotations

import customtkinter as ctk

# Window Dimensions
WINDOW_WIDTH = 1040
WINDOW_HEIGHT = 700
MIN_WIDTH = 860
MIN_HEIGHT = 540

# Color Palette (Dark Neutral Charcoal Gray Theme)
COLOR_BG_WINDOW = "#121417"          # Dark Charcoal Gray (replacing deep navy)
COLOR_BG_SIDEBAR = "#0c0e11"         # Deepest Dark Gray
COLOR_BG_CARD = "#1a1d24"            # Refined Panel/Card Dark Gray
COLOR_BG_CARD_HOVER = "#242832"      # Card Hover Dark Gray
COLOR_BG_CARD_SELECTED = "#1e2430"   # Selected item background
COLOR_BORDER_SELECTED = "#38bdf8"    # Selected item border
COLOR_BORDER = "#282c37"             # Clean Dark Gray Separator
COLOR_BORDER_SUBTLE = "#1e2129"      # Subtle separator

# Typography Colors
COLOR_TEXT_PRIMARY = "#f8fafc"       # Slate-50 Crisp White
COLOR_TEXT_MUTED = "#94a3b8"         # Slate-400 Neutral Muted
COLOR_TEXT_DIM = "#64748b"           # Slate-500 Dim

# Functional Brand & Status Colors
COLOR_ACCENT = "#2563eb"             # Royal Brand Blue (Buttons & Badges)
COLOR_ACCENT_HOVER = "#1d4ed8"       # Darker Royal Blue
COLOR_SUCCESS = "#10b981"            # Emerald-500 (Used strictly for live active/done states)
COLOR_SUCCESS_HOVER = "#059669"
COLOR_WARNING = "#f59e0b"            # Amber-500 (Used strictly for expired/action needed)
COLOR_WARNING_BG = "#381d06"         # Dark Amber Card Background
COLOR_WARNING_BORDER = "#f59e0b"
COLOR_ERROR = "#ef4444"              # Red-500
COLOR_ERROR_HOVER = "#dc2626"
COLOR_TORRENT = "#a855f7"            # Purple-500
COLOR_WEB = "#38bdf8"                # Sky Blue-400

# Progress Bar Color Tokens
COLOR_PROGRESS_ACTIVE = "#38bdf8"    # Sky Blue
COLOR_PROGRESS_DONE = "#10b981"      # Emerald Green
COLOR_PROGRESS_PAUSED = "#64748b"    # Neutral Slate Gray
COLOR_PROGRESS_EXPIRED = "#f59e0b"   # Amber Orange
COLOR_PROGRESS_ERROR = "#ef4444"     # Rose Red

# Button Secondary & Ghost Colors (Dark Gray)
COLOR_BTN_SECONDARY = "#22262f"      # Dark Gray Button Background
COLOR_BTN_SECONDARY_HOVER = "#2e3340" # Slightly lighter dark gray hover
COLOR_BTN_GHOST = "transparent"
COLOR_BTN_GHOST_HOVER = "#242832"

# Corner Radii
RADIUS_CONTAINER = 10
RADIUS_CARD = 8
RADIUS_BUTTON = 6
RADIUS_INPUT = 6
RADIUS_PROGRESS = 4
RADIUS_PILL = 12

# Typography with added weight (Confident, bold hierarchy)
def get_title_font() -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=16, weight="bold")

def get_section_font() -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=13, weight="bold")

def get_body_font() -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=11, weight="bold")

def get_bold_font() -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=11, weight="bold")

def get_badge_font() -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=10, weight="bold")

def get_mono_font() -> ctk.CTkFont:
    return ctk.CTkFont(family="Consolas", size=10, weight="bold")

def get_caption_font() -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=10, weight="bold")
