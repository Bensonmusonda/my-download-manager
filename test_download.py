"""
Test suite for Smart Downloader Core, Multi-Connection Chunking, and Link Refreshing.
Starts a local HTTP server with Range request support, simulated 403 expiry,
tests parallel chunking, interruption, resumption, and file integrity.
"""

import http.server
import os
import shutil
import socketserver
import threading
import time
from pathlib import Path

from browser_session import make_session_headers
from downloader import download, DownloadStatus
from state import DownloadManifest, find_unfinished_downloads

TEST_DATA = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 15000  # 540 KB test payload
PORT = 8991
DOWNLOAD_DIR = Path("./test_downloads")


class MockRangeHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with RFC 7233 Range support and simulated 403 link expiration."""

    def do_GET(self):
        total_len = len(TEST_DATA)

        # Route 1: Standard downloadable file with full range support
        if self.path in ("/testfile.bin", "/fresh_link.bin", "/chunked_file.bin"):
            range_header = self.headers.get("Range")

            if range_header:
                # e.g., "bytes=1000-" or "bytes=0-499"
                bytes_range = range_header.replace("bytes=", "").split("-")
                start = int(bytes_range[0])
                end = int(bytes_range[1]) if bytes_range[1] else total_len - 1

                if start >= total_len:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total_len}")
                    self.end_headers()
                    return

                self.send_response(206)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Range", f"bytes {start}-{end}/{total_len}")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(TEST_DATA[start : end + 1])
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(total_len))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(TEST_DATA)

        # Route 2: Expired signed link (HTTP 403 Forbidden)
        elif self.path == "/expired_link.bin":
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Forbidden: Signed URL has expired.")

        # Route 3: Gone link (HTTP 410 Gone)
        elif self.path == "/gone_link.bin":
            self.send_response(410)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Gone: Download token is no longer valid.")

        else:
            self.send_error(404)

    def log_message(self, format, *args):
        # Quiet test server logs
        pass


def run_tests():
    # 1. Start test server
    server = socketserver.TCPServer(("127.0.0.1", PORT), MockRangeHTTPRequestHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    try:
        if DOWNLOAD_DIR.exists():
            shutil.rmtree(DOWNLOAD_DIR)
        DOWNLOAD_DIR.mkdir()

        headers = make_session_headers(None)

        # ── Test 1: Single-stream partial download and resume ─────────
        print("\n[Test 1] Simulating interrupted download with pre-created partial file...")
        target_file = DOWNLOAD_DIR / "testfile.bin"
        with open(target_file, "wb") as f:
            f.write(TEST_DATA[:50000])

        assert target_file.stat().st_size == 50000
        print(f"  Partial file created: {target_file.stat().st_size:,} bytes")

        result = download(
            url=f"http://127.0.0.1:{PORT}/testfile.bin",
            headers=headers,
            dest_dir=str(DOWNLOAD_DIR),
            filename="testfile.bin",
            min_chunk_size=1024 * 1024 * 100,  # Ensure single-stream for this test
        )
        assert result.status == DownloadStatus.COMPLETED, f"Download failed: {result.error}"
        assert target_file.stat().st_size == len(TEST_DATA)

        with open(target_file, "rb") as f:
            downloaded = f.read()
        assert downloaded == TEST_DATA, "Integrity check failed on resumed single stream!"
        print(f"  ✔ Resume complete: {len(downloaded):,} bytes. Integrity verified!")

        # ── Test 2: HTTP 416 on already-complete file ──────────────────
        print("\n[Test 2] Testing already-completed file...")
        result_re = download(
            url=f"http://127.0.0.1:{PORT}/testfile.bin",
            headers=headers,
            dest_dir=str(DOWNLOAD_DIR),
            filename="testfile.bin",
        )
        assert result_re.status == DownloadStatus.COMPLETED
        print("  ✔ Already completed download handled cleanly!")

        # ── Test 3: Multi-connection Speed Boosting (Chunking) ────────
        print("\n[Test 3] Testing Multi-Connection Speed Boosting (4 parallel chunks)...")
        chunked_target = DOWNLOAD_DIR / "chunked_file.bin"
        result_chunked = download(
            url=f"http://127.0.0.1:{PORT}/chunked_file.bin",
            headers=headers,
            dest_dir=str(DOWNLOAD_DIR),
            filename="chunked_file.bin",
            num_connections=4,
            min_chunk_size=10000,  # Lower threshold so our test payload activates chunking
        )
        assert result_chunked.status == DownloadStatus.COMPLETED, f"Chunked download failed: {result_chunked.error}"
        assert chunked_target.exists(), "Chunked target file was not created!"
        assert chunked_target.stat().st_size == len(TEST_DATA), "Chunked target file size mismatch!"

        with open(chunked_target, "rb") as f:
            chunked_data = f.read()
        assert chunked_data == TEST_DATA, "Multi-chunk stitched data integrity check failed!"
        print(f"  ✔ Multi-connection 4-chunk download & stitch complete! Final size: {len(chunked_data):,} bytes.")

        # ── Test 4: Expired Link Detection (HTTP 403) ───────────────────
        print("\n[Test 4] Testing Expired Link Detection (HTTP 403 Forbidden)...")
        expired_file = DOWNLOAD_DIR / "refresh_test.bin"
        # Pre-seed with 100,000 bytes
        with open(expired_file, "wb") as f:
            f.write(TEST_DATA[:100000])

        result_exp = download(
            url=f"http://127.0.0.1:{PORT}/expired_link.bin",
            headers=headers,
            dest_dir=str(DOWNLOAD_DIR),
            filename="refresh_test.bin",
        )
        assert result_exp.status == DownloadStatus.EXPIRED_URL, f"Expected EXPIRED_URL status, got {result_exp.status}"
        assert expired_file.exists(), "Partial file was deleted upon 403!"
        assert expired_file.stat().st_size == 100000, "Partial file was corrupted upon 403!"
        print(f"  ✔ Expired link detected gracefully (HTTP 403). Partial file preserved: {expired_file.stat().st_size:,} bytes.")

        # ── Test 5: Link Refresh with fresh URL and HTTP Range resume ──
        print("\n[Test 5] Testing Link Refresh: resuming partial file with fresh URL...")
        result_fresh = download(
            url=f"http://127.0.0.1:{PORT}/fresh_link.bin",
            headers=headers,
            dest_dir=str(DOWNLOAD_DIR),
            filename="refresh_test.bin",
            min_chunk_size=1024 * 1024 * 100,
        )
        assert result_fresh.status == DownloadStatus.COMPLETED, f"Resume with fresh URL failed: {result_fresh.error}"
        assert expired_file.stat().st_size == len(TEST_DATA), f"Refreshed download size mismatch: {expired_file.stat().st_size}"

        with open(expired_file, "rb") as f:
            refreshed_data = f.read()
        assert refreshed_data == TEST_DATA, "Data integrity check failed after link refresh!"
        print(f"  ✔ Seamless link refresh verified! Final size: {len(refreshed_data):,} bytes. 100% integrity match!")

        # ── Test 6: Multi-Connection Chunked Refresh & Unfinished Scan ─
        print("\n[Test 6] Testing Multi-Connection Chunk Interruption & State Manifest Scan...")
        multi_refresh_target = DOWNLOAD_DIR / "multi_refresh.bin"
        meta_file = DOWNLOAD_DIR / "multi_refresh.bin.meta.json"

        # Simulate 4 chunks where chunk 0 is done, chunk 1 is halfway, chunk 2 and 3 are empty
        chunk_len = (len(TEST_DATA) + 3) // 4
        chunk0_path = DOWNLOAD_DIR / "multi_refresh.bin.part.chunk0"
        chunk1_path = DOWNLOAD_DIR / "multi_refresh.bin.part.chunk1"
        chunk2_path = DOWNLOAD_DIR / "multi_refresh.bin.part.chunk2"
        chunk3_path = DOWNLOAD_DIR / "multi_refresh.bin.part.chunk3"

        # Chunk 0: full chunk
        with open(chunk0_path, "wb") as f:
            f.write(TEST_DATA[:chunk_len])
        # Chunk 1: half chunk
        with open(chunk1_path, "wb") as f:
            f.write(TEST_DATA[chunk_len : chunk_len + 10000])

        # Verify discovery of unfinished download
        unfinished = find_unfinished_downloads(DOWNLOAD_DIR)
        assert any(Path(u.target_file).name == "multi_refresh.bin" for u in unfinished), "Unfinished multi-chunk download not discovered!"
        print("  ✔ Unfinished multi-chunk download detected by scanner.")

        # Resume with fresh URL and 4 connections
        result_multi_resumed = download(
            url=f"http://127.0.0.1:{PORT}/fresh_link.bin",
            headers=headers,
            dest_dir=str(DOWNLOAD_DIR),
            filename="multi_refresh.bin",
            num_connections=4,
            min_chunk_size=10000,
        )
        assert result_multi_resumed.status == DownloadStatus.COMPLETED
        assert multi_refresh_target.stat().st_size == len(TEST_DATA)

        with open(multi_refresh_target, "rb") as f:
            multi_resumed_data = f.read()
        assert multi_resumed_data == TEST_DATA, "Multi-chunk resume data integrity failed!"
        print(f"  ✔ Multi-connection chunk resumption from existing state succeeded! Bit-for-bit verified.")

        print("\n=======================================================")
        print("🎉 ALL SPRINT 3 TESTS PASSED SUCCESSFULLY! (6/6 TESTS)")
        print("=======================================================\n")

    finally:
        server.shutdown()
        if DOWNLOAD_DIR.exists():
            shutil.rmtree(DOWNLOAD_DIR)


if __name__ == "__main__":
    run_tests()
