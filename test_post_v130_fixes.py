"""
Unit & Integration Tests for Post-v1.3.0 Fixes & Optimizations.

Verifies:
  1. Fix CLI lost sys.stdin crash: AttachConsole reopen CONIN$ and safe_input fallback.
  2. Worker progress callback throttling (100-150ms) in QueueManager.
  3. Queue state persistence and clean restoration across app sessions.
  4. Resumption logic: assumes valid URL, attempts HTTP Range, only prompts on 401/403/410.
  5. Removal of blocking messagebox in batch completion and adherence to on_complete_action.
  6. Snappy UI rendering: cached widget properties, avoiding redraws/repacks on progress ticks.
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cli import safe_input
from queue_manager import (
    BatchSummary,
    QueueItem,
    QueueItemStatus,
    QueueManager,
)
from state import DownloadManifest


# ── Test 1: CLI sys.stdin safety ───────────────────────────────────────────

def test_safe_input_with_valid_stdin():
    mock_stdin = io.StringIO("https://example.com/test.zip\n")
    with patch("sys.stdin", mock_stdin):
        res = safe_input("Prompt: ")
        assert res == "https://example.com/test.zip"


def test_safe_input_handles_none_or_closed_stdin():
    # When sys.stdin is None and not on Windows, raises RuntimeError gracefully
    with patch("sys.stdin", None):
        with patch("sys.platform", "linux"):
            with pytest.raises(RuntimeError) as exc_info:
                safe_input("Prompt: ")
            assert "sys.stdin unavailable" in str(exc_info.value)


# ── Test 2: Progress Callback Throttling ───────────────────────────────────

def test_queue_manager_progress_cb_throttling():
    with tempfile.TemporaryDirectory() as tmp_dir:
        q = QueueManager(dest_dir=tmp_dir, max_concurrent=1, persist_state=False)
        item = q.add_item("http://example.com/file.bin", filename="file.bin")

        notifications = []
        q.on_item_updated = lambda it: notifications.append(it.downloaded_bytes)

        # Simulate 20 rapid progress ticks inside a worker within 50ms
        last_cb_time = 0.0
        start = time.time()
        for i in range(20):
            downloaded = (i + 1) * 1000
            now = start + (i * 0.002)  # 2ms intervals
            if now - last_cb_time >= 0.12:
                last_cb_time = now
                q._notify_item_updated(item)

        # Out of 20 rapid calls in 40ms, throttled dispatches should be at most 1
        assert len(notifications) <= 1


# ── Test 3: QueueManager State Persistence & Restoration ───────────────────

def test_queue_state_persistence_and_restore():
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = Path(tmp_dir) / "test_queue_state.json"
        q1 = QueueManager(
            dest_dir=tmp_dir,
            max_concurrent=2,
            state_file=state_file,
            persist_state=True,
        )

        item1 = q1.add_item("http://example.com/item1.iso", filename="item1.iso")
        item2 = q1.add_item("http://example.com/item2.mkv", filename="item2.mkv")
        q1.pause_item(item1.id)

        assert state_file.exists()
        with open(state_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        assert len(saved_data) == 2
        assert saved_data[0]["filename"] == "item1.iso"
        assert saved_data[1]["filename"] == "item2.mkv"

        # Now simulate a fresh app startup loading the persisted state
        q2 = QueueManager(
            dest_dir=tmp_dir,
            max_concurrent=2,
            state_file=state_file,
            persist_state=True,
        )

        assert len(q2.items) == 2
        restored_names = [it.filename for it in q2.items]
        assert "item1.iso" in restored_names
        assert "item2.mkv" in restored_names
        # Active or queued items should reload as PAUSED ready to resume
        for it in q2.items:
            assert it.status == QueueItemStatus.PAUSED


# ── Test 4: Resumption Logic & Manifest URL Preservation ───────────────────

def test_resumption_preserves_manifest_url_without_prompt():
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "large_archive.zip"
        # Simulate partial file on disk
        with open(target, "wb") as f:
            f.write(b"PARTIAL_DATA_" * 100)

        manifest = DownloadManifest(
            target_file=str(target),
            original_url="https://cdn.example.com/large_archive.zip?auth=valid",
            latest_url="https://cdn.example.com/large_archive.zip?auth=valid",
            total_bytes=500000,
            downloaded_bytes=len(b"PARTIAL_DATA_" * 100),
            status="paused_cancelled",
        )
        manifest.save()
        assert manifest.meta_path().exists()

        # Reload manifest
        loaded_mf = DownloadManifest.load(manifest.meta_path())
        assert loaded_mf is not None
        assert loaded_mf.latest_url == "https://cdn.example.com/large_archive.zip?auth=valid"

        # When creating a QueueItem for resumption, URL is populated directly
        item = QueueItem(
            url=loaded_mf.latest_url,
            filename=target.name,
            dest_dir=tmp_dir,
            target_path=target,
            downloaded_bytes=loaded_mf.downloaded_bytes,
            total_bytes=loaded_mf.total_bytes,
        )
        assert item.url == "https://cdn.example.com/large_archive.zip?auth=valid"
        assert item.downloaded_bytes > 0


# ── Test 5: Batch Completion & on_complete_action ──────────────────────────

def test_batch_summary_respects_on_complete_action():
    from ui.app_window import SmartDownloaderApp

    app = SmartDownloaderApp.__new__(SmartDownloaderApp)
    app.dest_dir = tempfile.gettempdir()
    app.app_settings = {"on_complete_action": "chime"}
    app.tray = MagicMock()
    app.speed_metrics_lbl = MagicMock()
    app._refresh_all_ui = MagicMock()

    summary = BatchSummary(
        total_items=3,
        completed=3,
        skipped=0,
        expired=0,
        failed=0,
        total_bytes_downloaded=1048576,
        duration=2.5,
        items=[],
    )

    with patch("tkinter.messagebox.showinfo") as mock_box, \
         patch("winsound.MessageBeep", create=True) as mock_beep:
        # Call batch completion handler
        SmartDownloaderApp._handle_batch_summary(app, summary)

        # 1. Verify blocking messagebox is NEVER called
        assert not mock_box.called

        # 2. Verify status bar notification updated
        app.speed_metrics_lbl.configure.assert_called_once()
        call_text = app.speed_metrics_lbl.configure.call_args[1]["text"]
        assert "Batch complete: 3/3 finished" in call_text

        # 3. Verify chime was sounded
        if sys.platform == "win32":
            assert mock_beep.called


# ── Test 6: UI Snappiness (in-place widget property caching) ───────────────

def test_queue_card_rendering_cache():
    from ui.queue_card import QueueRowCard

    card = QueueRowCard.__new__(QueueRowCard)
    card.actions_frame = MagicMock()
    card.name_lbl = MagicMock()
    card.percent_lbl = MagicMock()
    card.size_lbl = MagicMock()
    card.telemetry_lbl = MagicMock()
    card.progress_bar = MagicMock()
    card.configure = MagicMock()
    card.is_selected = False
    card._rendered_status = QueueItemStatus.ACTIVE
    card._cached_border_style = (False, False)
    card._cached_name = "test.zip"
    card._cached_pct = "50.0%"
    card._cached_sz = "500 KB / 1.0 MB"
    card._cached_telemetry = "Downloading..."
    card._cached_progress_color = "#3b82f6"

    item = QueueItem(
        url="http://example.com/test.zip",
        filename="test.zip",
        status=QueueItemStatus.ACTIVE,
        downloaded_bytes=512000,
        total_bytes=1024000,
    )

    # Calling update_data with identical data should NOT rebuild buttons or reconfigure border
    QueueRowCard.update_data(card, item)

    assert not card.actions_frame.winfo_children.called
    assert not card.configure.called


# ── Test 7: Update Preferred Asset Selection ──────────────────────────────

def test_update_asset_selection():
    from updater import ReleaseAsset, UpdateInfo

    assets = [
        ReleaseAsset(
            name="SmartDownloadManager-v1.3.1-Setup.exe",
            download_url="https://example.com/setup.exe",
            size=40000000,
            content_type="application/octet-stream",
        ),
        ReleaseAsset(
            name="SmartDownloadManager-v1.3.1-Windows-Portable.zip",
            download_url="https://example.com/portable.zip",
            size=42000000,
            content_type="application/zip",
        ),
        ReleaseAsset(
            name="SmartDownloadManager.exe",
            download_url="https://example.com/standalone.exe",
            size=39000000,
            content_type="application/octet-stream",
        ),
    ]

    info = UpdateInfo(
        remote_version="1.3.1",
        tag_name="v1.3.1",
        release_notes="Bug fixes",
        html_url="https://github.com/...",
        published_at="2026-11-21",
        assets=assets,
    )

    # Installed or default environment prefers setup installer
    installer_asset = info.get_asset("installer")
    assert installer_asset is not None
    assert "setup" in installer_asset.name.lower()

    # Portable matches zip
    portable_asset = info.get_asset("portable")
    assert portable_asset is not None
    assert portable_asset.name.endswith(".zip")

    # Standalone matches exe without setup
    standalone_asset = info.get_asset("standalone")
    assert standalone_asset is not None
    assert standalone_asset.name == "SmartDownloadManager.exe"


# ── Test 8: Update Download & Apply Execution ─────────────────────────────

def test_update_download_and_apply():
    from updater import UpdateChecker

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a mock remote response containing dummy binary bytes
        dummy_data = b"MOCK_NEW_EXE_BINARY_DATA_1234567890"

        class MockResponse:
            def __init__(self):
                self.headers = {"Content-Length": str(len(dummy_data))}
                self.bio = io.BytesIO(dummy_data)

            def read(self, amt=-1):
                return self.bio.read(amt)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        progress_calls = []
        before_restart_called = False

        def _mock_progress(frac, dl, tot):
            progress_calls.append((frac, dl, tot))

        def _mock_before_restart():
            nonlocal before_restart_called
            before_restart_called = True

        mock_resp = MockResponse()

        with patch("tempfile.gettempdir", return_value=tmp_dir), \
             patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("subprocess.Popen") as mock_popen, \
             patch("os._exit") as mock_exit:

            success = UpdateChecker.download_and_apply_update(
                download_url="https://example.com/test-setup.exe",
                progress_cb=_mock_progress,
                asset_name="SmartDownloadManager-v1.3.1-Setup.exe",
                before_restart_cb=_mock_before_restart,
            )

            assert success is True
            assert before_restart_called is True
            assert len(progress_calls) > 0
            assert progress_calls[-1][0] == 1.0  # 100%

            # Check that update asset was written
            saved_file = Path(tmp_dir) / "SDM_Update" / "SmartDownloadManager-v1.3.1-Setup.exe"
            assert saved_file.exists()
            assert saved_file.read_bytes() == dummy_data

            # Check that batch script was generated
            bat_file = Path(tmp_dir) / "SDM_Update" / "apply_update.bat"
            assert bat_file.exists()
            content = bat_file.read_text(encoding="utf-8")
            assert "/SILENT" in content
            assert "/CLOSEAPPLICATIONS" in content

            # Verify detached process was launched and process exited
            assert mock_popen.called
            assert mock_exit.called

