# Multi-Connection Speed Boosting (Parallel Chunking)

Smart Download Manager accelerates large downloads by splitting them into concurrent connections, saturating your bandwidth and bypassing per-connection speed caps set by some servers.

---

## 1. How It Works

```
Remote File on Server (e.g. 600 MB)
├── Chunk 0: [0 MB – 100 MB]     ── Thread 1 ──>  file.iso.part.chunk0
├── Chunk 1: [100 MB – 200 MB]   ── Thread 2 ──>  file.iso.part.chunk1
├── Chunk 2: [200 MB – 300 MB]   ── Thread 3 ──>  file.iso.part.chunk2
├── Chunk 3: [300 MB – 400 MB]   ── Thread 4 ──>  file.iso.part.chunk3
├── Chunk 4: [400 MB – 500 MB]   ── Thread 5 ──>  file.iso.part.chunk4
└── Chunk 5: [500 MB – 600 MB]   ── Thread 6 ──>  file.iso.part.chunk5

                   ⬇ When All Chunks Complete ⬇
        Stitched into final file: downloads/file.iso (600 MB)
```

1. **Server Probe**: Before downloading, the engine sends a lightweight `Range: bytes=0-0` request.
2. **Range Support Verification**:
   - If the server responds with HTTP `206 Partial Content`, byte ranges are supported.
   - If the total file size exceeds **50 MB** (default), multi-connection mode activates automatically.
3. **Chunk Allocation**:
   - The file is divided into $N$ byte-ranges (default: 6 parallel connections).
   - Each chunk streams to an isolated temporary file: `<filename>.part.chunk{i}`.
4. **Stitching**:
   - Once all worker threads reach 100% completion, the engine concatenates the chunks in exact numerical order into the final file using buffered streaming.
   - Chunk files and metadata are cleaned up automatically.

---

## 2. Surviving Network Drops and Pauses

What happens if a network glitch occurs or your link expires halfway through?
- Each chunk temporary file maintains its own byte count on disk.
- If Chunk 0 and Chunk 1 are finished, but Chunk 2 has downloaded only 40%:
  - On retry or URL refresh, **Chunk 0 and Chunk 1 are skipped completely**.
  - **Chunk 2 resumes from byte 40%** using `Range: bytes=<chunk2_start + current_disk_bytes>-<chunk2_end>`.
  - Zero bandwidth is wasted!

---

## 3. Tuning Concurrency & Thresholds

### Number of Connections (`-c` / `--connections`)
Default is **6** connections (recommended 4 to 8):
```powershell
# Use 8 parallel connections for maximum throughput:
python __main__.py "https://example.com/big_file.zip" -c 8

# Use 4 connections on moderate connections:
python __main__.py "https://example.com/big_file.zip" -c 4
```

### Minimum File Size Threshold (`-m` / `--min-chunk-size`)
By default, files smaller than **50 MB** use a single connection to avoid unnecessary server overhead. You can lower or raise this threshold:
```powershell
# Enable chunking for files starting at 20 MB:
python __main__.py "https://example.com/file.zip" -m 20
```

---

## 4. Single-Connection Fallback

If the remote server:
- Does not support byte ranges (responds with HTTP 200 instead of 206), or
- Does not report `Content-Length`, or
- The file is smaller than the threshold (<= 50MB),

The manager automatically falls back to single-stream download with exponential back-off retries and standard byte-range resume support.

