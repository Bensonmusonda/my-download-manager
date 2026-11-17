"""
Smart Download Manager — browser_session.py

Extracts active cookies (especially cf_clearance) and the matching User-Agent
from local browsers or from the companion browser extension so that download
requests look like authentic browser traffic to Cloudflare.

Supports:
  • Live browser extension sessions (instant, bypassing Windows file locks & App-Bound Encryption)
  • Chrome, Firefox, and Edge offline profile scans
  • Manual cookie / User-Agent injection
"""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# In-memory store for live sessions received from the Chrome extension
_LIVE_EXTENSION_SESSIONS: dict[str, BrowserSession] = {}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BrowserSession:
    """Holds cookies + headers harvested from a real browser."""
    cookies: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    browser_name: str = ""

    @property
    def has_cf_clearance(self) -> bool:
        return "cf_clearance" in self.cookies

    def as_curl_cookies(self) -> str:
        """Format cookies as a single '; '-joined string for curl headers."""
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


# ---------------------------------------------------------------------------
# Default User-Agent strings per browser
# ---------------------------------------------------------------------------

_DEFAULT_USER_AGENTS: dict[str, str] = {
    "chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "firefox": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
        "Gecko/20100101 Firefox/133.0"
    ),
    "edge": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
}


# ---------------------------------------------------------------------------
# Live Extension Session Management
# ---------------------------------------------------------------------------

def store_live_session(domain: str, cookies_str: str, user_agent: str = "") -> BrowserSession:
    """
    Store or update live session cookies received from the browser extension.
    Domain is normalized (e.g. 'example.com').
    """
    domain = domain.lower().lstrip(".").split(":")[0]
    cookies_dict: dict[str, str] = {}

    for part in cookies_str.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            cookies_dict[k.strip()] = v.strip()

    ua = user_agent.strip() or _DEFAULT_USER_AGENTS["chrome"]
    session = BrowserSession(
        cookies=cookies_dict,
        user_agent=ua,
        browser_name="chrome-extension",
    )
    _LIVE_EXTENSION_SESSIONS[domain] = session
    log.info(
        f"[Extension Bridge] Stored live session for {domain} with {len(cookies_dict)} cookies "
        + ("(cf_clearance ✅)" if session.has_cf_clearance else "(no cf_clearance)")
    )
    return session


def get_live_session(domain: str) -> Optional[BrowserSession]:
    """Look up active session for domain from the extension cache."""
    clean_domain = domain.lower().lstrip(".").split(":")[0]
    # Check exact match
    if clean_domain in _LIVE_EXTENSION_SESSIONS:
        return _LIVE_EXTENSION_SESSIONS[clean_domain]
    # Check suffix match (e.g. dl.example.com matching example.com)
    for stored_domain, session in _LIVE_EXTENSION_SESSIONS.items():
        if clean_domain.endswith(stored_domain) or stored_domain.endswith(clean_domain):
            return session
    return None


# ---------------------------------------------------------------------------
# Cookie extraction helpers (Offline profile scan)
# ---------------------------------------------------------------------------

def _cookies_for_domain(jar: CookieJar, domain: str) -> dict[str, str]:
    """Filter a CookieJar down to cookies that match *domain* (suffix match)."""
    result: dict[str, str] = {}
    for cookie in jar:
        cookie_domain = cookie.domain.lstrip(".")
        if domain.endswith(cookie_domain) or cookie_domain.endswith(domain):
            result[cookie.name] = cookie.value
    return result


def _try_browser(
    browser_fn,
    browser_name: str,
    domain: str,
) -> Optional[BrowserSession]:
    """Attempt to load cookies from one browser profile on disk."""
    try:
        jar = browser_fn(domain_name=f".{domain}")
        cookies = _cookies_for_domain(jar, domain)
        if not cookies:
            log.debug(f"[{browser_name}] No cookies found for {domain}")
            return None

        session = BrowserSession(
            cookies=cookies,
            user_agent=_DEFAULT_USER_AGENTS.get(browser_name, ""),
            browser_name=browser_name,
        )
        log.info(
            f"[{browser_name}] Loaded {len(cookies)} cookie(s) for {domain}"
            + (" — cf_clearance FOUND" if session.has_cf_clearance else "")
        )
        return session
    except PermissionError:
        log.warning(
            f"[{browser_name}] Cookie DB is locked — "
            "use the Smart Downloader browser extension for live sessions."
        )
    except Exception as exc:
        log.debug(f"[{browser_name}] Cookie extraction failed: {exc}")
    return None


def _read_chrome_ua() -> Optional[str]:
    """Try to read the real Chrome version from its Local State file."""
    if platform.system() != "Windows":
        return None
    local_state = os.path.expandvars(
        r"%LOCALAPPDATA%\Google\Chrome\User Data\Local State"
    )
    try:
        with open(local_state, encoding="utf-8") as fh:
            data = json.load(fh)
        version = data.get("browser", {}).get("last_version")
        if version:
            return (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{version} Safari/537.36"
            )
    except Exception:
        pass
    return None


def _safe_import_bc3():
    """Safely import browser_cookie3, avoiding WMI/shadowcopy COM errors on Windows."""
    try:
        import browser_cookie3 as bc3
        return bc3
    except Exception as exc:
        import sys
        sys.modules['shadowcopy'] = None
        try:
            import browser_cookie3 as bc3
            return bc3
        except Exception as retry_exc:
            log.warning(f"Could not load browser_cookie3: {retry_exc}")
            return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_browser_session(
    url: str,
    manual_cookie: Optional[str] = None,
    manual_ua: Optional[str] = None,
) -> Optional[BrowserSession]:
    """
    Get active browser cookies and User-Agent for *url*:
    1. Check for manual overrides
    2. Check for live session received from the browser extension (Highest priority)
    3. Fallback to scanning local browser profile SQLite files (Chrome, Edge, Firefox)
    """
    # 1. Check for manual overrides first
    if manual_cookie:
        cookies_dict = {}
        for part in manual_cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies_dict[k.strip()] = v.strip()
        return BrowserSession(
            cookies=cookies_dict,
            user_agent=manual_ua or _DEFAULT_USER_AGENTS["chrome"],
            browser_name="manual",
        )

    domain = urlparse(url).netloc
    if not domain:
        log.error(f"Cannot parse domain from URL: {url}")
        return None
    domain = domain.split(":")[0]

    # 2. Check for live extension session (Highest priority & bypassing file locks)
    live = get_live_session(domain)
    if live:
        log.info(f"Using live session from Browser Extension for {domain}")
        return live

    # Fast path for local / loopback test endpoints: skip offline browser disk scan
    if domain in ("127.0.0.1", "localhost", "::1"):
        return BrowserSession(
            cookies={},
            user_agent=_DEFAULT_USER_AGENTS["chrome"],
            browser_name="local",
        )

    # 3. Fallback to offline disk profile scan
    bc3 = _safe_import_bc3()
    if bc3 is None:
        log.warning("browser-cookie3 is unavailable. Continuing without browser cookies.")
        return None

    browsers = [
        (bc3.chrome, "chrome"),
        (bc3.edge,   "edge"),
        (bc3.firefox, "firefox"),
    ]

    best: Optional[BrowserSession] = None

    for fn, name in browsers:
        session = _try_browser(fn, name, domain)
        if session is None:
            continue

        if name == "chrome":
            real_ua = _read_chrome_ua()
            if real_ua:
                session.user_agent = real_ua

        if session.has_cf_clearance:
            return session

        if best is None:
            best = session

    return best


def make_session_headers(session: Optional[BrowserSession]) -> dict[str, str]:
    """Build request headers from a BrowserSession (or sensible defaults)."""
    headers: dict[str, str] = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if session:
        headers["User-Agent"] = session.user_agent
        if session.cookies:
            headers["Cookie"] = session.as_curl_cookies()
    else:
        headers["User-Agent"] = _DEFAULT_USER_AGENTS["chrome"]
    return headers
