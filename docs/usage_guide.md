# CLI Usage & Command Reference

Smart Download Manager supports both an interactive terminal menu and non-interactive command-line flags.

---

## Command Syntax

```powershell
python __main__.py [URL] [OPTIONS]
```

Or using the full virtual environment path:

```powershell
& "d:\Projects\my_smart_downloader\.venv312\Scripts\python.exe" d:\Projects\my_smart_downloader\__main__.py [URL] [OPTIONS]
```

---

## Command-Line Options

| Flag | Full Option | Default | Description |
| :--- | :--- | :--- | :--- |
| `[url]` | Positional | `None` | Optional URL. If passed, starts downloading immediately without displaying the main menu. |
| `-d` | `--dest <DIR>` | `./downloads` | Local directory where files and chunks are saved. |
| `-c` | `--connections <N>` | `6` | Number of concurrent connections/threads for files >50MB (range 2 to 16). |
| `-m` | `--min-chunk-size <MB>` | `50` | File size threshold in megabytes to activate parallel chunking. Files smaller than this use single-stream resume. |
| `-u` | `--update-url <PATH>` | `None` | Direct shortcut to point a fresh URL at an unfinished file on disk. |
| `-v` | `--verbose` | `False` | Enable detailed debug logging (HTTP headers, chunk worker state, retries). |
| `-h` | `--help` | — | Display help message and exit. |

---

## Practical Examples

### 1. Download to a Custom Directory
```powershell
python __main__.py "https://example.com/archive.iso" -d "D:\MyDownloads"
```

### 2. Maximize Speed with 8 Connections
For high-bandwidth internet connections, boost parallel threads:
```powershell
python __main__.py "https://example.com/large_video.mkv" -c 8
```

### 3. Lower the Chunking Threshold
Enable parallel multi-chunking on smaller files (e.g., anything larger than 10MB):
```powershell
python __main__.py "https://example.com/data.tar.gz" -m 10
```

### 4. Resume an Unfinished Download with a New Link
If you have an unfinished partial file (e.g., `downloads/backup.zip`) and you got a fresh signed link:
```powershell
python __main__.py -u "downloads/backup.zip"
```

---

## Interactive Menu Workflows

When launched without arguments (`python __main__.py`), the main menu gives you 3 options:

### Option 1: Download a new URL
Prompts for a download link. Auto-detects filename, inspects browser cookies, probes server capabilities, and begins streaming.

### Option 2: Update URL for existing file (Resume unfinished)
1. Automatically scans the `downloads/` directory for any unfinished files or interrupted chunks.
2. Displays a table of incomplete downloads with downloaded byte size and status.
3. Lets you select a file by index, or enter `C` to supply a custom file path.
4. Asks for the fresh URL, automatically fetches cookies for the new domain, and resumes the remaining bytes.

### Option 3: Exit
Gracefully exits the program.

