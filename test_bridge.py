"""
Test suite for Browser Extension Bridge Server.
Tests HTTP endpoints, CORS headers, live session storage, and download callbacks.
"""

import json
import time
import urllib.request
from urllib.error import HTTPError

import browser_session
from bridge_server import BridgeServer

TEST_PORT = 8993


def run_bridge_tests():
    print("\n--- Running Browser Extension Bridge Tests ---")

    download_received = []
    session_received = []

    def on_download(data):
        download_received.append(data)

    def on_session(data):
        session_received.append(data)

    # 1. Start test bridge server
    server = BridgeServer(
        port=TEST_PORT,
        on_download=on_download,
        on_session=on_session,
    )
    assert server.start(), "Failed to start BridgeServer!"
    time.sleep(0.3)

    base_url = f"http://127.0.0.1:{TEST_PORT}"

    try:
        # Test 1: Health check & CORS
        print("[Test 1] Testing GET /status endpoint...")
        req = urllib.request.Request(f"{base_url}/status")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"
            print("  ✔ /status returned 200 OK with valid CORS headers!")

        # Test 2: Sending live Cloudflare session from extension
        print("[Test 2] Testing POST /session (sharing cf_clearance)...")
        session_payload = {
            "domain": "my-protected-site.com",
            "cookies": "cf_clearance=test_clearance_abc123; session_id=xyz987",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
            "has_cf_clearance": True,
        }
        req = urllib.request.Request(
            f"{base_url}/session",
            data=json.dumps(session_payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            res_data = json.loads(resp.read().decode())
            assert res_data["status"] == "ok"

        assert len(session_received) == 1
        print("  ✔ Bridge received and dispatched session callback!")

        # Verify that browser_session module now uses the live session!
        live_session = browser_session.get_browser_session("https://my-protected-site.com/file.zip")
        assert live_session is not None, "Failed to retrieve live session!"
        assert live_session.has_cf_clearance, "cf_clearance cookie missing from live session!"
        assert live_session.cookies.get("cf_clearance") == "test_clearance_abc123"
        assert live_session.user_agent == "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"
        assert live_session.browser_name == "chrome-extension"
        print("  ✔ browser_session.get_browser_session() successfully prioritized the live extension session!")

        # Test 3: Sending download task from extension
        print("[Test 3] Testing POST /download (dispatching task from Chrome)...")
        download_payload = {
            "url": "https://my-protected-site.com/big_file.iso",
            "cookies": "cf_clearance=test_clearance_abc123",
            "user_agent": "Mozilla/5.0 Chrome/131",
            "filename": "big_file.iso",
        }
        req = urllib.request.Request(
            f"{base_url}/download",
            data=json.dumps(download_payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

        assert len(download_received) == 1
        assert download_received[0]["url"] == "https://my-protected-site.com/big_file.iso"
        print("  ✔ Download task received and queued by bridge!")

        print("\n=======================================================")
        print("🎉 ALL EXTENSION BRIDGE TESTS PASSED! (3/3 TESTS)")
        print("=======================================================\n")

    finally:
        server.stop()


if __name__ == "__main__":
    run_bridge_tests()

