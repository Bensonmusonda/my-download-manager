# Quickstart Guide

This guide gets you up and running with Smart Download Manager in under a minute.

---

## 1. Prerequisites

The project comes with a pre-configured Windows CPython 3.12 environment located at `.venv312\`.

> [!IMPORTANT]
> Always execute using `.venv312\Scripts\python.exe` because `curl_cffi` requires pre-compiled Windows AMD64 native binaries with `libcurl-impersonate.dll`.

---

## 2. Launch the Interactive Downloader

Open PowerShell or Command Prompt in the repository folder:

```powershell
& "d:\Projects\my_smart_downloader\.venv312\Scripts\python.exe" d:\Projects\my_smart_downloader\__main__.py
```

You will see the welcome banner and the main menu:

```text
╔════════════════════════════════════════════════════════╗
║         ⬇  Smart Download Manager  v0.3              ║
║  Cloudflare-ready · Multi-Connection · Link Refresh   ║
╚════════════════════════════════════════════════════════╝

Select an option:
  1. Download a new URL
  2. Update URL for existing file (Resume unfinished)
  3. Exit (or q)

  ➤ Choice [1]:
```

---

## 3. Starting Your First Download

1. Choose option `1` (or press **Enter**).
2. Paste the download URL when prompted:
   ```text
   Enter download URL (or press Enter to go back):
     ➤  https://example.com/large_installer.zip
   ```
3. The downloader will:
   - Scan Chrome, Edge, and Firefox for valid session cookies (`cf_clearance`).
   - Probe the server for byte-range support and file size.
   - For files >50MB, split into 6 parallel connections for maximum download speed.
   - Display a real-time progress bar with combined download speed, completion %, and ETA.
   - Save the file cleanly to `downloads/`.

---

## 4. One-Line Direct Download

You can also bypass the menu and start downloading immediately by passing the URL as an argument:

```powershell
& "d:\Projects\my_smart_downloader\.venv312\Scripts\python.exe" d:\Projects\my_smart_downloader\__main__.py https://example.com/large_installer.zip
```

---

## 5. Batch Downloads from File (`urls.txt`)

To download a list of files in batch with concurrent queue management:

```powershell
& "d:\Projects\my_smart_downloader\.venv312\Scripts\python.exe" d:\Projects\my_smart_downloader\__main__.py -f urls.txt -q 2
```

Format of `urls.txt`:
```text
# Supports URL, URL | filename, or URL | filename | referer
https://example.com/file1.zip
https://example.com/file2.zip | custom_name.zip
https://cdn.example.org/stream.mp4 | video1.mp4 | https://portal.example.org/
```
Pre-existing completed files are automatically skipped, and if any link expires (HTTP 403), it is paused safely while the remaining queue continues to finish!

