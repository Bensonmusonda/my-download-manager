# Smart Download Manager

Smart Download Manager is a high-reliability, multi-protocol download manager built in Python. It is specifically engineered to handle Cloudflare-protected origins, accelerate large downloads via multi-connection parallel chunking, and recover interrupted transfers caused by expiring signed URLs (HTTP 401, 403 Forbidden, and 410 Gone).

The system includes a companion Manifest V3 browser extension, a concurrent background queue engine, an interactive command-line interface, and a modern CustomTkinter desktop interface.

---

## Key Capabilities

- **Cloudflare and Bot Protection Bypass**: Utilizes `curl_cffi` for browser-grade TLS/JA3/JA4 fingerprint impersonation matching genuine Chrome browser handshakes.
- **Companion Browser Extension**: Manifest V3 extension for Chrome, Edge, and Brave. Captures live `cf_clearance` cookies and user sessions directly from memory, auto-catches browser downloads, and communicates with the manager over a local loopback bridge.
- **Universal Anti-Hotlink Referer Engine**: Automatically determines and supplies appropriate `Referer` headers required by content delivery networks to prevent 403 hotlinking restrictions.
- **Multi-Connection Speed Boosting**: Automatically probes server byte-range capabilities (`Accept-Ranges: bytes`). Files larger than 50MB are split into 4 to 8 parallel worker threads using HTTP Range requests, with chunks stitched upon completion.
- **Expired Signed Link Recovery**: When temporary download tokens expire mid-transfer (HTTP 401, 403, 410), partial data and chunks are preserved on disk. Users can supply a refreshed URL through the GUI or CLI to resume downloading remaining bytes.
- **Concurrent Background Queue & Batch Ingestion**: Supports batch processing from plain text files (`urls.txt`) with configurable worker concurrency, automatic skipping of already-completed files, non-blocking failure recovery, and structured summary reporting.
- **State Manifest Tracking**: Maintains download state in `.meta.json` manifests, allowing seamless resumption across process interruptions, network drops, and system restarts.
- **BitTorrent & Magnet Link Engine**: Integrated high-performance BitTorrent client (`libtorrent` 2.x) supporting `.torrent` files and `magnet:?xt=urn:btih:...` URIs, non-blocking metadata downloads, DHT, PeX, LSD, and fastresume state persistence.
- **Dual Interface**: Offers a dark-mode Windows 11 style desktop GUI (CustomTkinter) and a command-line interface with streaming progress indicators (Rich).
- **Pre-Built Windows Releases**: Ready-to-run Windows Installer (`.exe`), Portable ZIP bundle, and standalone binary with native file associations and protocol handlers.

---

## Downloads & Releases

Pre-compiled binary releases for Windows (x86_64) are published under [GitHub Releases](https://github.com/Bensonmusonda/my-download-manager/releases):

| Asset | Description |
| :--- | :--- |
| **`SmartDownloadManager-v1.0.0-Setup.exe`** | **Full Windows Installer**: Installs the desktop application, creates Start Menu & Desktop shortcuts, registers `.torrent` file association, and configures the `magnet:` protocol handler. |
| **`SmartDownloadManager-v1.0.0-Windows-Portable.zip`** | **Portable Archive**: Zero-install standalone package. Extract anywhere and launch `SmartDownloadManager.exe` immediately. |
| **`SmartDownloadManager.exe`** | **Standalone Executable**: Single application binary. |

---

## Architecture Overview

```
smart_downloader/
|-- extension/              Manifest V3 Chrome / Edge companion extension
|   |-- manifest.json       Extension manifest definition
|   |-- background.js       Background service worker for session and download events
|   |-- popup.html          Popup interface for session synchronization
|   `-- popup.js            Popup controller
|-- bridge_server.py        Local HTTP bridge server (127.0.0.1:8992) with CORS support
|-- browser_session.py      Live extension session cache and offline SQLite cookie harvest
|-- downloader.py           Core download engine (TLS impersonation, chunking, stitching)
|-- torrent_engine.py       BitTorrent & Magnet engine (libtorrent 2.x, DHT, PeX, fastresume)
|-- queue_manager.py        Concurrent background task queue and protocol routing engine
|-- state.py                Download state manifest models and incomplete file scanner
|-- gui.py                  CustomTkinter desktop graphical user interface
|-- cli.py                  Interactive and batch command-line interface
|-- __main__.py             Unified application entry point and flag parser
|-- docs/                   Technical and user documentation library
|-- test_download.py        Engine test suite (RFC 7233 range, chunking, link refresh)
|-- test_bridge.py          Extension bridge and session cache test suite
|-- test_queue.py           Queue concurrency, batch ingestion, and skip test suite
`-- test_torrent.py         BitTorrent loopback download, magnet, and fastresume test suite
```

---

## Installation & Requirements

### System Requirements
- Windows 10/11 (x86_64) or Linux/macOS
- Python 3.12 (CPython AMD64 recommended for pre-compiled `curl_cffi` wheels)

### Setup

1. Clone or download the repository to your local system:
   ```powershell
   git clone https://github.com/Bensonmusonda/my-download-manager
   cd my_smart_downloader
   ```

2. Create and activate a Python 3.12 virtual environment:
   ```powershell
   python -m venv .venv312
   .\.venv312\Scripts\Activate.ps1
   ```

3. Install project dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Usage Guide

### 1. Launching the Desktop GUI

```powershell
python __main__.py --gui
```
or directly:
```powershell
python gui.py
```

The GUI provides:
- Single download input with automatic Referer inference.
- Download Queue tab displaying queued, active, completed, skipped, and expired tasks with individual progress meters.
- Batch import button for loading `urls.txt` files.
- Concurrency selector (1, 2, 3, 4, or 6 simultaneous downloads).
- Unfinished Recovery tab for resuming incomplete downloads discovered on disk.
- Live Extension Bridge connection indicator.

---

### 2. Interactive Command-Line Interface

Run the application with no positional arguments to open the interactive terminal menu:

```powershell
python __main__.py
```

Options include:
1. Download a single URL.
2. Batch download from file (`urls.txt`).
3. Update URL for existing file (Resume unfinished).
4. Exit.

---

### 3. Direct Single Download via CLI

```powershell
python __main__.py https://example.com/large_archive.zip -d ./downloads -c 6
```

Parameters:
- `url`: Direct download URL or signed link.
- `-d, --dest`: Output directory (default: `./downloads`).
- `-c, --connections`: Number of parallel worker connections for files over 50MB (default: 6).
- `-m, --min-chunk-size`: Minimum file size in MB required to trigger multi-connection chunking (default: 50).

---

### 4. Batch Download from File (`urls.txt`)

Process multiple downloads sequentially or concurrently from a text file:

```powershell
python __main__.py -f urls.txt -q 2 -d ./downloads
```

Parameters:
- `-f, --file`: Path to the URLs batch file.
- `-q, --concurrent`: Maximum number of active parallel downloads (default: 2).

#### Batch File Syntax (`urls.txt`)

Lines beginning with `#` or `//` and blank lines are ignored. Each entry supports three formats:

```text
# Format 1: URL only
https://example.com/archive.zip

# Format 2: URL | Custom Filename
https://example.com/stream?id=9928 | episode_01.mp4

# Format 3: URL | Custom Filename | Anti-Hotlink Referer
https://cdn.example.org/asset.bin | release_v1.bin | https://portal.example.org/download
```

Features:
- Already-completed downloads matching remote file size are automatically skipped (`SKIPPED`).
- Expired links (HTTP 403) are paused safely without halting the remaining queue.
- A consolidated batch summary report is generated upon completion.

---

### 5. Resuming Interrupted Downloads with a Refreshed URL

If a download fails due to an expired token, pass the target file path along with `-u`:

```powershell
python __main__.py -u "./downloads/large_archive.zip"
```

The application prompts for the fresh URL, verifies partial bytes on disk, re-authenticates browser sessions, and resumes via HTTP Range.

---

## Companion Chrome Extension Setup

The companion extension enables one-click download capture and bypasses Windows file-locking constraints on browser cookie databases:

1. Open Chrome, Edge, or Brave and navigate to `chrome://extensions/`.
2. Enable **Developer mode** using the toggle switch in the upper right.
3. Click **Load unpacked** in the upper left.
4. Select the `extension/` directory from this repository.
5. The extension icon will appear in the toolbar. Clicking the icon transmits active tab cookies and user session headers to the local bridge server on `127.0.0.1:8992`.

---

## Running the Automated Test Suite

The project includes unit and integration tests covering the download engine, extension bridge, range resumption, and batch queue operations:

```powershell
# 1. Core engine tests (range resume, chunking, stitching, 403 handling)
python test_download.py

# 2. Browser extension bridge tests (HTTP endpoints, CORS preflight, session caching)
python test_bridge.py

# 3. Queue manager tests (batch parsing, sequential/concurrent processing, skip detection)
python test_queue.py

# 4. BitTorrent tests (magnet link parsing, loopback torrent transfer, fastresume persistence)
python test_torrent.py
```

---

## Technical Documentation

Detailed architecture specifications, component guides, and integration details are available in the [`docs/`](docs/) directory:

- [Quickstart Guide](docs/quickstart.md)
- [CLI Usage Guide](docs/usage_guide.md)
- [Desktop GUI Guide](docs/gui_guide.md)
- [Browser Extension Guide](docs/extension_guide.md)
- [Cloudflare Bypass Architecture](docs/cloudflare_bypass.md)
- [Multi-Connection Chunking](docs/multi_connection.md)
- [Link Refreshing Mechanism](docs/link_refreshing.md)
- [State Manifests and Persistence](docs/architecture.md)

---

## License

This software is distributed under the MIT License. See `LICENSE` for details.
