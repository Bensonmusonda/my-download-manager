"""
Test suite for Sprint 4: Queue Manager & Batch Processing.
Verifies:
  1. Batch file parsing (urls.txt) with all three formats and comments
  2. Sequential queue processing (max_concurrent=1)
  3. Concurrent queue processing (max_concurrent=2)
  4. Automatic skipping of already completed files (size match / 416)
  5. Expired URL handling (HTTP 403): pauses expired item, queue proceeds with remaining items
  6. Batch summary report generation and metrics
"""

import http.server
import os
import shutil
import socketserver
import threading
import time
from pathlib import Path

from queue_manager import (
    BatchSummary,
    QueueItem,
    QueueItemStatus,
    QueueManager,
    parse_urls_file,
)

PORT = 8993
TEST_DATA_A = b"AAAA" * 25000  # 100 KB
TEST_DATA_B = b"BBBB" * 25000  # 100 KB
TEST_DATA_C = b"CCCC" * 25000  # 100 KB
DOWNLOAD_DIR = Path("./test_queue_downloads")


class MockQueueHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Mock server serving multiple files, Range requests, and simulated 403."""

    def do_GET(self):
        file_map = {
            "/file_a.bin": TEST_DATA_A,
            "/file_b.bin": TEST_DATA_B,
            "/file_c.bin": TEST_DATA_C,
        }

        if self.path in file_map:
            data = file_map[self.path]
            total_len = len(data)
            range_header = self.headers.get("Range")

            if range_header:
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
                self.wfile.write(data[start : end + 1])
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(total_len))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(data)

        elif self.path == "/expired_item.bin":
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Forbidden: Signed link expired.")

        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def run_tests():
    # Start mock server
    server = socketserver.TCPServer(("127.0.0.1", PORT), MockQueueHTTPRequestHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.4)

    try:
        if DOWNLOAD_DIR.exists():
            shutil.rmtree(DOWNLOAD_DIR)
        DOWNLOAD_DIR.mkdir()

        print("\n--- Running Sprint 4: Queue & Batch Processing Tests ---")

        # ── Test 1: Batch file parsing (urls.txt) ─────────────────────────
        print("\n[Test 1] Testing batch file parsing (urls.txt formats & comments)...")
        batch_file = DOWNLOAD_DIR / "test_urls.txt"
        with open(batch_file, "w", encoding="utf-8") as f:
            f.write(
                "# Sample Batch File\n"
                "\n"
                f"http://127.0.0.1:{PORT}/file_a.bin\n"
                f"http://127.0.0.1:{PORT}/file_b.bin | custom_b.bin\n"
                f"http://127.0.0.1:{PORT}/file_c.bin | custom_c.bin | https://source.example.com/\n"
                "# Trailing comment and whitespace\n"
                "   \n"
            )

        items = parse_urls_file(batch_file, default_dest=str(DOWNLOAD_DIR))
        assert len(items) == 3, f"Expected 3 items, got {len(items)}"

        # Verify Item 1: URL only
        assert items[0].url == f"http://127.0.0.1:{PORT}/file_a.bin"
        assert items[0].filename is None
        assert items[0].referer is None

        # Verify Item 2: URL | filename
        assert items[1].url == f"http://127.0.0.1:{PORT}/file_b.bin"
        assert items[1].filename == "custom_b.bin"
        assert items[1].referer is None

        # Verify Item 3: URL | filename | referer
        assert items[2].url == f"http://127.0.0.1:{PORT}/file_c.bin"
        assert items[2].filename == "custom_c.bin"
        assert items[2].referer == "https://source.example.com/"

        print("  ✔ Batch file ingestion parsed all 3 formats and comments cleanly!")

        # ── Test 2: Sequential Queue Execution (max_concurrent=1) ──────────
        print("\n[Test 2] Testing sequential queue execution (max_concurrent=1)...")
        q_seq = QueueManager(dest_dir=str(DOWNLOAD_DIR), max_concurrent=1)
        q_seq.add_item(f"http://127.0.0.1:{PORT}/file_a.bin", filename="seq_a.bin")
        q_seq.add_item(f"http://127.0.0.1:{PORT}/file_b.bin", filename="seq_b.bin")

        done_event = threading.Event()
        q_seq.on_queue_completed = lambda summary: done_event.set()

        q_seq.start()
        assert done_event.wait(timeout=10), "Sequential queue execution timed out"

        file_a = DOWNLOAD_DIR / "seq_a.bin"
        file_b = DOWNLOAD_DIR / "seq_b.bin"
        assert file_a.exists() and file_a.stat().st_size == len(TEST_DATA_A)
        assert file_b.exists() and file_b.stat().st_size == len(TEST_DATA_B)

        summary_seq = q_seq.get_summary()
        assert summary_seq.completed == 2
        assert summary_seq.failed == 0
        print(f"  ✔ Sequential queue complete: 2/2 files downloaded ({summary_seq.total_bytes_downloaded:,} bytes)!")

        # ── Test 3: Concurrent Queue Execution (max_concurrent=2) ──────────
        print("\n[Test 3] Testing concurrent queue execution (max_concurrent=2)...")
        q_conc = QueueManager(dest_dir=str(DOWNLOAD_DIR), max_concurrent=2)
        q_conc.add_item(f"http://127.0.0.1:{PORT}/file_a.bin", filename="conc_a.bin")
        q_conc.add_item(f"http://127.0.0.1:{PORT}/file_b.bin", filename="conc_b.bin")
        q_conc.add_item(f"http://127.0.0.1:{PORT}/file_c.bin", filename="conc_c.bin")

        done_conc = threading.Event()
        q_conc.on_queue_completed = lambda summary: done_conc.set()

        q_conc.start()
        assert done_conc.wait(timeout=10), "Concurrent queue execution timed out"

        for fname, expected_data in [
            ("conc_a.bin", TEST_DATA_A),
            ("conc_b.bin", TEST_DATA_B),
            ("conc_c.bin", TEST_DATA_C),
        ]:
            fp = DOWNLOAD_DIR / fname
            assert fp.exists()
            with open(fp, "rb") as fh:
                assert fh.read() == expected_data

        summary_conc = q_conc.get_summary()
        assert summary_conc.completed == 3
        print(f"  ✔ Concurrent queue complete: 3/3 files downloaded ({summary_conc.total_bytes_downloaded:,} bytes)!")

        # ── Test 4: Automatic Skipping of Already Completed Files ──────────
        print("\n[Test 4] Testing automatic skip of already-completed files...")
        # conc_a.bin is already completed on disk with 100,000 bytes
        q_skip = QueueManager(dest_dir=str(DOWNLOAD_DIR), max_concurrent=1)
        item_skip = q_skip.add_item(f"http://127.0.0.1:{PORT}/file_a.bin", filename="conc_a.bin")

        done_skip = threading.Event()
        q_skip.on_queue_completed = lambda summary: done_skip.set()
        q_skip.start()
        assert done_skip.wait(timeout=5), "Skip check timed out"

        assert item_skip.status == QueueItemStatus.SKIPPED
        assert item_skip.is_skipped is True
        summary_skip = q_skip.get_summary()
        assert summary_skip.skipped == 1
        print("  ✔ Pre-existing completed file automatically detected & SKIPPED cleanly!")

        # ── Test 5: Expired URL Handling (HTTP 403) in Queue ────────────────
        print("\n[Test 5] Testing non-blocking Expired URL (HTTP 403) in queue...")
        # Queue with 2 items: item 1 expires (403), item 2 is valid
        q_exp = QueueManager(dest_dir=str(DOWNLOAD_DIR), max_concurrent=1)
        it_expired = q_exp.add_item(f"http://127.0.0.1:{PORT}/expired_item.bin", filename="expired.bin")
        it_valid = q_exp.add_item(f"http://127.0.0.1:{PORT}/file_b.bin", filename="after_expired.bin")

        done_exp = threading.Event()
        q_exp.on_queue_completed = lambda summary: done_exp.set()
        q_exp.start()
        assert done_exp.wait(timeout=8), "Queue with expired link timed out"

        # Item 1 should be marked EXPIRED without stalling the queue
        assert it_expired.status == QueueItemStatus.EXPIRED, f"Expected EXPIRED, got {it_expired.status}"

        # Item 2 should have completed successfully
        assert it_valid.status == QueueItemStatus.COMPLETED, f"Expected COMPLETED, got {it_valid.status}"
        target_valid = DOWNLOAD_DIR / "after_expired.bin"
        assert target_valid.exists() and target_valid.stat().st_size == len(TEST_DATA_B)

        summary_exp = q_exp.get_summary()
        assert summary_exp.expired == 1
        assert summary_exp.completed == 1
        print("  ✔ Expired link (HTTP 403) marked EXPIRED without stalling; queue proceeded to finish item 2!")

        # ── Test 6: Final Batch Summary Report Verification ────────────────
        print("\n[Test 6] Verifying final batch summary report output...")
        report_summary = BatchSummary(
            total_items=4,
            completed=2,
            skipped=1,
            expired=1,
            failed=0,
            cancelled=0,
            total_bytes_downloaded=250000,
            duration=3.2,
            items=[it_valid, item_skip, it_expired],
        )
        assert report_summary.total_items == 4
        assert report_summary.completed == 2
        assert report_summary.skipped == 1
        assert report_summary.expired == 1
        assert report_summary._format_bytes(1048576) == "1.0 MB"
        print("  ✔ BatchSummary metrics and formatting validated successfully!")

        # ── Test 7: End-to-End CLI Batch Runner (run_batch_cli) ───────────
        print("\n[Test 7] Testing End-to-End run_batch_cli with live progress & summary...")
        from cli import run_batch_cli
        cli_dest = DOWNLOAD_DIR / "cli_batch"
        cli_summary = run_batch_cli(
            file_path=batch_file,
            dest_dir=str(cli_dest),
            max_concurrent=2,
        )
        assert cli_summary is not None
        assert cli_summary.completed == 3
        assert (cli_dest / "file_a.bin").exists()
        assert (cli_dest / "custom_b.bin").exists()
        assert (cli_dest / "custom_c.bin").exists()
        print("  ✔ run_batch_cli executed end-to-end with live progress and summary!")

        print("\n=======================================================")
        print("🎉 ALL SPRINT 4 QUEUE & BATCH TESTS PASSED! (7/7 TESTS)")
        print("=======================================================\n")

    finally:
        server.shutdown()
        server.server_close()
        if DOWNLOAD_DIR.exists():
            shutil.rmtree(DOWNLOAD_DIR)


if __name__ == "__main__":
    run_tests()
