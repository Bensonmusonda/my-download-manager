# Desktop GUI Guide (CustomTkinter)

Smart Download Manager features a modern, dark-mode desktop GUI built with **CustomTkinter**. It provides real-time download visual feedback, connection controls, link refreshing prompts, and an unfinished download recovery browser.

---

## 1. Launching the GUI

Launch the GUI using either of the following commands:

```powershell
# Directly with gui.py:
& "d:\Projects\my_smart_downloader\.venv312\Scripts\python.exe" d:\Projects\my_smart_downloader\gui.py

# Or via the --gui / -g flag on __main__.py:
& "d:\Projects\my_smart_downloader\.venv312\Scripts\python.exe" d:\Projects\my_smart_downloader\__main__.py -g
```

---

## 2. Interface Features & Layout

```
╔══════════════════════════════════════════════════════════════════════╗
║  ⬇ Smart Download Manager                                             ║
║  Cloudflare-Ready · Multi-Connection Speed Boosting · Expired Refresher║
╠══════════════════════════════════════════════════════════════════════╣
║  [ Download Configuration Card ]                                     ║
║  URL:  [ https://example.com/large_archive.zip                     ] ║
║  Dest: [ D:\Projects\my_smart_downloader\downloads  ] [ Browse... ] ║
║  Connections: [ 6 (Recommended) ▼ ]   Chunk Threshold: [ 50 MB ▼ ]   ║
║                                  [ Pause/Cancel ] [ Start Download ] ║
╠══════════════════════════════════════════════════════════════════════╣
║  [ Active Progress Card ]                                            ║
║  large_archive.zip                 Status: Downloading (x6)...       ║
║  ████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░       ║
║  450.0 MB / 1.0 GB (45.0%)               34.2 MB/s         ETA: 00:16 ║
╠══════════════════════════════════════════════════════════════════════╣
║  [ ⚠️ Expired Link Alert Banner — Appears Only When 403 Occurs ]      ║
║  ⚠️ Link Expired (HTTP 401/403/410). Your partial file is safe!      ║
║  New URL: [ https://example.com/large_archive.zip?token=fresh...   ] ║
║  [ 🔄 Resume With Fresh URL ]  [ Dismiss / Keep Paused ]             ║
╠══════════════════════════════════════════════════════════════════════╣
║  [ 📂 Unfinished Downloads on Disk ]               [ Refresh Scan ]  ║
║  • ubuntu-24.iso (1.2 GB / 4.2 GB) · paused_expired [ Update & Resume]║
║  • backup.tar.gz (450 MB)          · paused_cancelled [ Update & Resume]║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 3. Key GUI Workflows

### A. Downloading with Cloudflare & Multi-Connection
1. Paste your URL into the **Download URL** box.
2. Select your desired number of parallel connections (default **6**) and minimum chunk threshold (default **50 MB**).
3. Click **Start Download**.
4. The status badge will indicate `Harvesting browser session...`, checking for `cf_clearance` cookies in Chrome, Edge, and Firefox.
5. The progress bar updates in real time with combined multi-thread transfer speed and estimated time remaining.

### B. Resuming Expired Signed URLs (HTTP 403/410)
1. If the server revokes or expires the download token mid-stream:
   - The worker threads pause gracefully.
   - All chunks on disk are preserved.
   - The amber **⚠️ Signed URL Expired** banner slides in above the progress card.
2. Go to your browser, click download again to generate a new signed URL, and copy it.
3. Paste the new URL into the alert card's input box.
4. Click **🔄 Resume With Fresh URL**.
5. The manager re-harvests cookies for the domain, checks the existing byte count on disk, and seamlessly resumes remaining bytes.

### C. Recovering Unfinished Downloads
At the bottom of the window, the **Unfinished Downloads on Disk** panel automatically scans your save directory for any incomplete downloads:
1. Click **Update URL & Resume** next to any listed unfinished file.
2. The file is selected in the active panel and the URL input is activated.
3. Paste the fresh link and click **Resume** to complete the file.

