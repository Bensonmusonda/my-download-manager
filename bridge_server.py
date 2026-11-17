"""
Smart Download Manager — bridge_server.py

Lightweight HTTP server running on 127.0.0.1:8992.
Listens for incoming session cookies (cf_clearance) and download tasks
sent by the companion browser extension.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse

import browser_session

log = logging.getLogger(__name__)

DEFAULT_BRIDGE_PORT = 8992


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """Handles requests from the Chrome extension with full CORS support."""

    on_download_callback: Optional[Callable[[dict], None]] = None
    on_session_callback: Optional[Callable[[dict], None]] = None

    def _set_cors_headers(self, status: int = 200, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        """Respond to CORS preflight requests."""
        self._set_cors_headers(200)

    def do_GET(self):
        """Health check endpoint for the extension."""
        parsed = urlparse(self.path)
        if parsed.path in ("/status", "/health", "/"):
            self._set_cors_headers(200)
            payload = {
                "status": "ok",
                "app": "Smart Download Manager",
                "version": "0.3",
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        """Receive download tasks or browser sessions."""
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        try:
            data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as exc:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"error": f"Invalid JSON: {exc}"}).encode("utf-8"))
            return

        if parsed.path == "/download":
            log.info(f"Received download from browser extension: {data.get('url')}")

            # Store cookies in memory cache
            url = data.get("url", "")
            cookies_str = data.get("cookies", "")
            user_agent = data.get("user_agent", "")
            if url and cookies_str:
                domain = urlparse(url).netloc.split(":")[0]
                browser_session.store_live_session(domain, cookies_str, user_agent)

            if BridgeRequestHandler.on_download_callback:
                try:
                    BridgeRequestHandler.on_download_callback(data)
                except Exception as exc:
                    log.error(f"Error in on_download_callback: {exc}")

            self._set_cors_headers(200)
            self.wfile.write(json.dumps({"status": "ok", "message": "Download task queued"}).encode("utf-8"))

        elif parsed.path == "/session":
            domain = data.get("domain", "")
            url = data.get("url", "")
            cookies_str = data.get("cookies", "")
            user_agent = data.get("user_agent", "")

            if not domain and url:
                domain = urlparse(url).netloc.split(":")[0]

            log.info(f"Received session from browser extension for domain: {domain}")
            if domain and cookies_str:
                browser_session.store_live_session(domain, cookies_str, user_agent)

            if BridgeRequestHandler.on_session_callback:
                try:
                    BridgeRequestHandler.on_session_callback(data)
                except Exception as exc:
                    log.error(f"Error in on_session_callback: {exc}")

            self._set_cors_headers(200)
            self.wfile.write(json.dumps({"status": "ok", "message": "Session received"}).encode("utf-8"))

        else:
            self.send_error(404, "Endpoint not found")

    def log_message(self, format, *args):
        # Quiet standard HTTP access logs
        pass


class BridgeServer:
    """Manages the background HTTP server lifecycle."""

    def __init__(
        self,
        port: int = DEFAULT_BRIDGE_PORT,
        on_download: Optional[Callable[[dict], None]] = None,
        on_session: Optional[Callable[[dict], None]] = None,
    ):
        self.port = port
        BridgeRequestHandler.on_download_callback = on_download
        BridgeRequestHandler.on_session_callback = on_session
        self.httpd: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self) -> bool:
        """Start server in background thread."""
        try:
            self.httpd = HTTPServer(("127.0.0.1", self.port), BridgeRequestHandler)
            self.is_running = True
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()
            log.info(f"Browser Extension Bridge running on http://127.0.0.1:{self.port}")
            return True
        except Exception as exc:
            log.warning(f"Could not start Extension Bridge on port {self.port}: {exc}")
            self.is_running = False
            return False

    def stop(self) -> None:
        """Shut down the server."""
        if self.httpd:
            self.is_running = False
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            log.info("Browser Extension Bridge stopped.")

