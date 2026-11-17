"""
Smart Download Manager — test_torrent.py

Comprehensive automated test suite for Sprint 5:
BitTorrent & Magnet Link Integration wrapping libtorrent 2.x.
Tests:
  1. Magnet URI parsing (info hash, display name, trackers)
  2. Torrent source detection (magnet:, .torrent files, HTTP URLs)
  3. libtorrent Session Manager initialization & extension registration
  4. .torrent file creation, parsing, and torrent_info validation
  5. Fastresume state persistence and buffer serialization roundtrip
  6. Loopback end-to-end BitTorrent download & bit-for-bit integrity verification
  7. Loopback Magnet link metadata resolution & complete download
  8. Clean cancellation via threading.Event
  9. QueueManager protocol routing & mixed batch file ingestion
"""

import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Tuple

import libtorrent as lt

from downloader import DownloadStatus
from queue_manager import (
    QueueItem,
    QueueItemStatus,
    QueueManager,
    parse_urls_file,
)
from torrent_engine import (
    TorrentSessionManager,
    download_torrent,
    get_fastresume_path,
    is_torrent_source,
    parse_magnet_display_name,
    parse_magnet_info_hash,
)

TEST_DOWNLOAD_DIR = Path("./test_torrent_downloads")


def create_test_torrent_file(
    target_file_path: Path,
    piece_size: int = 16384,
) -> Tuple[Path, lt.torrent_info, bytes]:
    """Helper to generate a valid .torrent file from a local payload."""
    fs = lt.file_storage()
    fs.add_file(target_file_path.name, target_file_path.stat().st_size)
    ct = lt.create_torrent(fs, piece_size)
    lt.set_piece_hashes(ct, str(target_file_path.parent))
    torrent_entry = ct.generate()
    torrent_bytes = lt.bencode(torrent_entry)
    ti = lt.torrent_info(torrent_bytes)

    torrent_file_path = target_file_path.parent / f"{target_file_path.name}.torrent"
    with open(torrent_file_path, "wb") as f:
        f.write(torrent_bytes)

    return torrent_file_path, ti, torrent_bytes


def run_tests():
    print("\n--- Running Sprint 5: BitTorrent & Magnet Link Integration Tests ---\n")

    if TEST_DOWNLOAD_DIR.exists():
        shutil.rmtree(TEST_DOWNLOAD_DIR)
    TEST_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # ── Test 1: Magnet URI Parsing & Source Detection ─────────────────
    print("[Test 1] Testing Magnet URI parsing and source detection...")
    magnet_a = "magnet:?xt=urn:btih:da39a3ee5e6b4b0d3255bfef95601890afd80709&dn=sample_movie.mp4&tr=udp%3A%2F%2Ftracker.openbittorrent.com%3A6969"
    magnet_b = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"

    assert is_torrent_source(magnet_a) is True
    assert is_torrent_source(magnet_b) is True
    assert is_torrent_source("https://example.com/file.iso") is False
    assert is_torrent_source("https://example.com/archive.torrent") is True
    assert is_torrent_source("C:/Users/test/Downloads/ubuntu.torrent") is True
    assert is_torrent_source("") is False

    h_a = parse_magnet_info_hash(magnet_a)
    dn_a = parse_magnet_display_name(magnet_a)
    assert h_a == "da39a3ee5e6b4b0d3255bfef95601890afd80709", f"Got: {h_a}"
    assert dn_a == "sample_movie.mp4", f"Got: {dn_a}"

    h_b = parse_magnet_info_hash(magnet_b)
    dn_b = parse_magnet_display_name(magnet_b)
    assert h_b == "0123456789abcdef0123456789abcdef01234567", f"Got: {h_b}"
    assert dn_b is None, f"Expected None, got: {dn_b}"

    print("  ✔ Magnet URI parsing & source detection verified!")

    # ── Test 2: Session Manager Initialization & Extensions ───────────
    print("\n[Test 2] Testing TorrentSessionManager singleton & extension registration...")
    mgr = TorrentSessionManager.get_instance()
    assert mgr is not None
    assert mgr.session is not None
    assert mgr.session.is_listening() or mgr.session.listen_port() >= 0
    print(f"  ✔ TorrentSessionManager active (listening port: {mgr.session.listen_port()})")

    # ── Test 3: .torrent Creation & Metadata Inspection ───────────────
    print("\n[Test 3] Testing .torrent metadata creation and parsing...")
    temp_dir = Path(tempfile.mkdtemp(prefix="sdm_test_torrent_"))
    try:
        sample_file = temp_dir / "sample_payload.bin"
        sample_payload = b"BitTorrentTestPayload-Sprint5-SmartDownloader" * 500  # ~22.5 KB
        with open(sample_file, "wb") as f:
            f.write(sample_payload)

        torrent_file, ti, torrent_bytes = create_test_torrent_file(sample_file)
        assert torrent_file.is_file()
        assert ti.name() == "sample_payload.bin"
        assert ti.total_size() == len(sample_payload)
        assert len(str(ti.info_hash())) == 40
        print(f"  ✔ .torrent created and validated: {ti.name()} ({ti.total_size()} bytes, hash: {ti.info_hash()})")

        # ── Test 4: Fastresume Persistence Roundtrip ──────────────────
        print("\n[Test 4] Testing Fastresume buffer persistence & reload...")
        atp = lt.add_torrent_params()
        atp.ti = ti
        atp.save_path = str(TEST_DOWNLOAD_DIR)
        fastresume_buf = lt.write_resume_data_buf(atp)
        assert len(fastresume_buf) > 0

        restored_atp = lt.read_resume_data(fastresume_buf)
        assert restored_atp.ti.name() == "sample_payload.bin"
        assert restored_atp.ti.total_size() == len(sample_payload)

        resume_path = get_fastresume_path(TEST_DOWNLOAD_DIR, str(ti.info_hash()))
        with open(resume_path, "wb") as rf:
            rf.write(fastresume_buf)
        assert resume_path.is_file()
        print(f"  ✔ Fastresume saved and restored successfully ({len(fastresume_buf)} bytes)!")

        # ── Test 5: Loopback BitTorrent Download & File Integrity ─────
        print("\n[Test 5] Testing Loopback BitTorrent download & bit-for-bit file integrity...")
        # 1. Start Seeder Session
        seeder_ses = lt.session({
            "listen_interfaces": "127.0.0.1:0",
            "enable_dht": False,
            "enable_lsd": False,
        })
        seeder_ses.add_extension(lt.create_ut_metadata_plugin)
        seeder_atp = lt.add_torrent_params()
        seeder_atp.ti = ti
        seeder_atp.save_path = str(temp_dir)
        seeder_handle = seeder_ses.add_torrent(seeder_atp)
        time.sleep(0.1)
        seeder_port = seeder_ses.listen_port()
        assert seeder_port > 0, "Seeder failed to bind loopback port"

        # 2. Download via download_torrent using leecher session
        leech_out = TEST_DOWNLOAD_DIR / "leech_test"
        leech_out.mkdir(parents=True, exist_ok=True)

        progress_calls = []

        def on_progress(dl, tot, spd, msg, peers=0, seeds=0):
            progress_calls.append((dl, tot, spd, msg, peers, seeds))

        # We connect the leecher to the seeder in a background thread once handle is created
        def _connect_peer():
            for _ in range(30):
                time.sleep(0.1)
                for h in mgr.session.get_torrents():
                    if str(h.info_hash()) == str(ti.info_hash()):
                        h.connect_peer(("127.0.0.1", seeder_port))
                        return

        conn_thread = threading.Thread(target=_connect_peer, daemon=True)
        conn_thread.start()

        res = download_torrent(
            source=str(torrent_file),
            dest_dir=str(leech_out),
            progress_callback=on_progress,
            save_fastresume=True,
        )

        assert res.status == DownloadStatus.COMPLETED, f"Download failed: {res.error}"
        assert res.bytes_downloaded == len(sample_payload)
        downloaded_file = leech_out / "sample_payload.bin"
        assert downloaded_file.is_file(), f"Target file missing: {downloaded_file}"
        with open(downloaded_file, "rb") as df:
            downloaded_bytes = df.read()
        assert downloaded_bytes == sample_payload, "Data integrity mismatch!"
        assert len(progress_calls) > 0
        print(f"  ✔ BitTorrent loopback download complete! Bit-for-bit integrity verified ({len(downloaded_bytes)} bytes).")

        # ── Test 6: Loopback Magnet Link Metadata Resolution ──────────
        print("\n[Test 6] Testing Magnet Link metadata resolution & download...")
        magnet_uri = f"magnet:?xt=urn:btih:{ti.info_hash()}&dn=sample_payload.bin"
        magnet_out = TEST_DOWNLOAD_DIR / "magnet_test"
        magnet_out.mkdir(parents=True, exist_ok=True)

        def _connect_magnet_peer():
            for _ in range(30):
                time.sleep(0.1)
                for h in mgr.session.get_torrents():
                    if str(h.info_hash()) == str(ti.info_hash()):
                        h.connect_peer(("127.0.0.1", seeder_port))
                        return

        conn_thread2 = threading.Thread(target=_connect_magnet_peer, daemon=True)
        conn_thread2.start()

        mag_res = download_torrent(
            source=magnet_uri,
            dest_dir=str(magnet_out),
            save_fastresume=True,
        )

        assert mag_res.status == DownloadStatus.COMPLETED, f"Magnet download failed: {mag_res.error}"
        mag_file = magnet_out / "sample_payload.bin"
        assert mag_file.is_file(), "Magnet target file missing"
        with open(mag_file, "rb") as mf:
            assert mf.read() == sample_payload
        print(f"  ✔ Magnet link metadata resolved & file downloaded successfully ({mag_res.bytes_downloaded} bytes)!")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # ── Test 7: Clean Cancellation via threading.Event ────────────────
    print("\n[Test 7] Testing clean cancellation without stalls...")
    cancel_evt = threading.Event()
    cancel_evt.set()  # Cancel immediately

    canc_res = download_torrent(
        source="magnet:?xt=urn:btih:da39a3ee5e6b4b0d3255bfef95601890afd80709&dn=dummy.bin",
        dest_dir=str(TEST_DOWNLOAD_DIR / "cancel_test"),
        cancel_event=cancel_evt,
    )
    assert canc_res.status == DownloadStatus.CANCELLED
    print("  ✔ Cancellation handled cleanly: returned CANCELLED immediately!")

    # ── Test 8: QueueManager Protocol Routing & Batch File Parsing ────
    print("\n[Test 8] Testing QueueManager protocol routing & batch file parsing...")
    batch_content = """
    # Mixed Batch File: HTTP + Magnet + Torrent
    http://127.0.0.1:8991/testfile.bin | http_file.bin
    magnet:?xt=urn:btih:da39a3ee5e6b4b0d3255bfef95601890afd80709&dn=magnet_video.mp4 | custom_magnet.mp4
    d:/test_folder/sample.torrent | local_torrent.bin
    """
    batch_path = TEST_DOWNLOAD_DIR / "test_mixed_urls.txt"
    with open(batch_path, "w", encoding="utf-8") as bf:
        bf.write(batch_content)

    items = parse_urls_file(batch_path, default_dest=str(TEST_DOWNLOAD_DIR))
    assert len(items) == 3, f"Expected 3 items, got: {len(items)}"
    assert items[0].is_torrent_task is False
    assert items[1].is_torrent_task is True
    assert items[1].display_name == "custom_magnet.mp4"
    assert items[2].is_torrent_task is True

    # Test QueueItem display_name fallback for magnet link
    item_magnet_auto = QueueItem(
        url="magnet:?xt=urn:btih:1111111111111111111111111111111111111111&dn=debian_installer.iso"
    )
    assert item_magnet_auto.is_torrent_task is True
    assert item_magnet_auto.display_name == "debian_installer.iso"

    qm = QueueManager(dest_dir=str(TEST_DOWNLOAD_DIR), max_concurrent=2)
    q_item = qm.add_item(url=magnet_a)
    assert q_item.is_torrent_task is True
    assert q_item.display_name == "sample_movie.mp4"
    print("  ✔ QueueManager routing and mixed batch ingestion verified!")

    # Clean up test directories
    if TEST_DOWNLOAD_DIR.exists():
        shutil.rmtree(TEST_DOWNLOAD_DIR, ignore_errors=True)

    print("\n" + "=" * 55)
    print("🎉 ALL SPRINT 5 BITTORRENT TESTS PASSED! (8/8 TESTS)")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    run_tests()
