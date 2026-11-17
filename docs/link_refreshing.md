# Expired Link Refreshing & Resume Guide

Many modern file hosting services (AWS S3, Cloudflare R2, Google Cloud Storage, Rapidgator, 1fichier, Gofile, etc.) issue temporary **signed URLs** protected by short-lived authorization tokens (valid for e.g. 1–4 hours).

If a large download takes longer than the token lifespan, or if your connection drops and the token expires before retry, standard downloaders crash or wipe out your partial file with an HTTP 403 error.

Smart Download Manager is designed to make expired link refreshing seamless.

---

## 1. How Expiration Detection Works

The engine continuously monitors all incoming HTTP responses across all worker connections:
- Status codes **401 Unauthorized**, **403 Forbidden**, or **410 Gone** are intercepted immediately.
- The manager halts all active worker threads cleanly.
- **Your partial file and temporary chunk files are never deleted or truncated.**
- The current byte progress is committed to `<filename>.meta.json`.

---

## 2. In-Stream Terminal Prompt

When an expiration is detected mid-download, the manager pauses and prompts you directly in the terminal:

```text
⏳ Link expired (HTTP 401/403/410). Partial file safe at D:\Projects\my_smart_downloader\downloads\bigfile.iso
(475,200,000 bytes saved so far)

Link expired. Paste a fresh URL to resume (or press Enter to skip): 
```

### Scenario A: You paste a fresh URL
1. Go back to your browser, click download again to generate a fresh signed URL, and copy it.
2. Paste the URL into the terminal prompt.
3. The downloader will:
   - Automatically extract fresh cookies (`cf_clearance`, session cookies) matching the new URL's domain.
   - Verify the existing byte count on disk.
   - Send HTTP `Range: bytes=<existing_bytes>-` to request **only** the remaining bytes.
   - Seamlessly continue where you left off.

### Scenario B: You press Enter (or skip)
If you don't have a new URL immediately:
1. Press **Enter** (or type `s`).
2. The download pauses safely. All chunk files and metadata remain intact on your disk.
3. You can close your computer, reboot, or resume days later!

---

## 3. Resuming Unfinished Files Anytime (Option 2)

If you previously closed or skipped a paused download, you can resume it anytime:

1. Launch the downloader:
   ```powershell
   python __main__.py
   ```
2. Select Option **[2]**: `Update URL for existing file (Resume unfinished)`.
3. The downloader scans the download folder and shows detected partial files:
   ```text
   Unfinished Downloads Detected
   ┌────┬────────────────┬──────────────┬────────────────┐
   │  # │ Filename       │ Downloaded   │ Status         │
   ├────┼────────────────┼──────────────┼────────────────┤
   │  1 │ ubuntu-24.iso  │ 1.4 / 4.2 GB │ paused_expired │
   │  2 │ backup.tar     │ 450.0 MB     │ paused_expired │
   └────┴────────────────┴──────────────┴────────────────┘
   Select a file number from above, enter C to specify a custom path, or B to go back:
   ```
4. Enter `1` and paste your new URL.
5. The downloader validates the partial file on disk and completes the remaining bytes.

