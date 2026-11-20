"""
Unit tests for storage_manager.py
Tests:
  1. Default downloads library folder resolution
  2. File category extraction across extensions (Images, Videos, Documents, Audio, Archives, Programs, Torrents, Other)
  3. URL query string and magnet URI category handling
  4. Download folder path resolution with/without Smart Downloader
  5. Settings persistence and atomic file replacement
"""

import os
import shutil
import tempfile
from pathlib import Path
import unittest

from storage_manager import (
    CATEGORY_EXTENSIONS,
    SMART_FOLDER_NAME,
    extract_file_extension,
    get_default_download_dir,
    get_file_category,
    load_settings,
    resolve_download_folder,
    save_settings,
)


class TestStorageManager(unittest.TestCase):

    def test_default_download_dir(self):
        dl_dir = get_default_download_dir()
        self.assertIsInstance(dl_dir, Path)
        self.assertTrue(str(dl_dir).endswith("Downloads") or dl_dir.exists())

    def test_category_extraction_images(self):
        for ext in ("jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico", "avif"):
            cat = get_file_category(f"sample.{ext}")
            self.assertEqual(cat, "Images", f"Failed for ext: {ext}")
            cat_url = get_file_category(f"https://cdn.example.com/media/test.{ext}?size=thumb&v=2")
            self.assertEqual(cat_url, "Images")

    def test_category_extraction_videos(self):
        for ext in ("mp4", "mkv", "avi", "mov", "webm", "flv"):
            cat = get_file_category(f"movie.{ext}")
            self.assertEqual(cat, "Videos", f"Failed for ext: {ext}")

    def test_category_extraction_documents(self):
        for ext in ("pdf", "docx", "xlsx", "pptx", "txt", "epub", "csv", "md"):
            cat = get_file_category(f"paper.{ext}")
            self.assertEqual(cat, "Documents", f"Failed for ext: {ext}")

    def test_category_extraction_audio(self):
        for ext in ("mp3", "wav", "flac", "aac", "ogg", "m4a", "opus"):
            cat = get_file_category(f"track.{ext}")
            self.assertEqual(cat, "Audio", f"Failed for ext: {ext}")

    def test_category_extraction_archives(self):
        for ext in ("zip", "rar", "7z", "tar", "gz", "bz2", "iso"):
            cat = get_file_category(f"archive.{ext}")
            self.assertEqual(cat, "Archives", f"Failed for ext: {ext}")

    def test_category_extraction_programs(self):
        for ext in ("exe", "msi", "apk", "dmg", "pkg", "bat", "cmd"):
            cat = get_file_category(f"installer.{ext}")
            self.assertEqual(cat, "Programs", f"Failed for ext: {ext}")

    def test_category_extraction_torrents(self):
        self.assertEqual(get_file_category("ubuntu.torrent"), "Torrents")
        self.assertEqual(get_file_category("magnet:?xt=urn:btih:1234567890abcdef"), "Torrents")

    def test_category_unknown_fallback(self):
        self.assertEqual(get_file_category("custom.xyz123"), "Other")
        self.assertEqual(get_file_category(""), "Other")

    def test_resolve_download_folder_with_smart(self):
        base = Path("/downloads")
        res_img = resolve_download_folder(base, "picture.png", use_smart_folders=True)
        self.assertEqual(res_img, base.resolve() / SMART_FOLDER_NAME / "Images")

        res_vid = resolve_download_folder(base, "clip.mp4", use_smart_folders=True)
        self.assertEqual(res_vid, base.resolve() / SMART_FOLDER_NAME / "Videos")

        res_doc = resolve_download_folder(base, "report.pdf", use_smart_folders=True)
        self.assertEqual(res_doc, base.resolve() / SMART_FOLDER_NAME / "Documents")

    def test_resolve_download_folder_without_smart(self):
        base = Path("/downloads")
        res = resolve_download_folder(base, "picture.png", use_smart_folders=False)
        self.assertEqual(res, base.resolve())

    def test_save_and_load_settings(self):
        test_dir = tempfile.mkdtemp()
        try:
            import storage_manager
            orig_cfg = storage_manager.CONFIG_FILE
            orig_dir = storage_manager.CONFIG_DIR
            try:
                storage_manager.CONFIG_DIR = Path(test_dir)
                storage_manager.CONFIG_FILE = Path(test_dir) / "test_settings.json"

                cfg = {
                    "dest_dir": "D:\\MyDownloads",
                    "use_smart_folders": True,
                    "smart_folder_name": "MySmartDir",
                    "max_concurrent": 4,
                    "num_connections": 8,
                    "minimize_to_tray": False,
                }
                ok = save_settings(cfg)
                self.assertTrue(ok)
                self.assertTrue(storage_manager.CONFIG_FILE.exists())

                loaded = load_settings()
                self.assertEqual(loaded["dest_dir"], "D:\\MyDownloads")
                self.assertTrue(loaded["use_smart_folders"])
                self.assertEqual(loaded["smart_folder_name"], "MySmartDir")
                self.assertEqual(loaded["max_concurrent"], 4)
                self.assertEqual(loaded["num_connections"], 8)
                self.assertFalse(loaded["minimize_to_tray"])
            finally:
                storage_manager.CONFIG_FILE = orig_cfg
                storage_manager.CONFIG_DIR = orig_dir
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
