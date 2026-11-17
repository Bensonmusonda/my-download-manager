"""
Smart Download Manager — downloader.py

Core download engine using curl_cffi for browser-grade TLS fingerprinting.
Features:
  • Automatic byte-range resumption (HTTP Range header)
  • Anti-hotlink Referer auto-detection (for CDNs like uwucdn, kwik, animepahe)
  • Multi-connection speed boosting (parallel chunk downloading for large files)
  • Expired signed URL detection (HTTP 403, 410, 401) with clean pause & state save
  • Streaming progress bar via Rich with aggregated multi-thread transfer speed
  • Non-blocking progress callbacks and cancel events for GUI integration
  • Configurable retries with exponential back-off
  • Clean chunk stitching and partial-file safety
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from state import ChunkState, DownloadManifest

log = logging.getLogger(__name__)
console = Console()

# ---------------------------------------------------------------------------
# Constants & configuration
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1024 * 256              # 256 KiB per read buffer
DEFAULT_MAX_RETRIES = 10             # retry attempts before giving up
INITIAL_BACKOFF_SECS = 2.0           # first retry waits this long
MAX_BACKOFF_SECS = 60.0              # cap on exponential back-off
CONNECT_TIMEOUT = 30                 # seconds
READ_TIMEOUT = 120                   # seconds

MULTI_CHUNK_MIN_SIZE = 50 * 1024 * 1024   # 50 MB threshold for parallel chunking
DEFAULT_NUM_CONNECTIONS = 6               # 4-8 parallel connections


class DownloadStatus(Enum):
    """Outcome of a download attempt."""
    COMPLETED = auto()
    FAILED = auto()
    EXPIRED_URL = auto()             # HTTP 403 / 410 / signed-URL expiry
    CANCELLED = auto()               # User paused or cancelled


@dataclass
class DownloadResult:
    """Returned by download() with outcome details."""
    status: DownloadStatus
    path: Path
    bytes_downloaded: int = 0
    total_size: Optional[int] = None
    manifest: Optional[DownloadManifest] = None
    error: Optional[str] = None


class _ExpiredURLError(Exception):
    """Raised when server returns 403/410/401 — signed URL expired."""


# ---------------------------------------------------------------------------
# Filename & Header helpers
# ---------------------------------------------------------------------------

def filename_from_url(url: str) -> str:
    """
    Derive a human-friendly filename from a URL.
    Strips query strings and fragments, URL-decodes, and falls back to
    'download' when the path is empty.
    """
    parsed = urlparse(url)
    # Check if 'file' query parameter is present (common in video CDNs like uwucdn)
    if "file=" in parsed.query:
        for part in parsed.query.split("&"):
            if part.startswith("file="):
                val = unquote(part.split("=", 1)[1])
                if val:
                    return val

    name = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    if not name:
        name = "download"
    return name


def filename_from_headers(headers: dict[str, str]) -> Optional[str]:
    """Extract filename from Content-Disposition header if present."""
    cd = headers.get("Content-Disposition") or headers.get("content-disposition")
    if not cd:
        return None
    # match filename*=UTF-8''filename or filename="filename"
    m_star = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", cd, re.IGNORECASE)
    if m_star:
        return unquote(m_star.group(1).strip('"\''))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip('"\''))
    return None


def infer_referer(url: str, custom_referer: Optional[str] = None) -> Optional[str]:
    """
    Determine the required Referer header for CDNs with anti-hotlinking.
    
    Priority order:
    1. Explicit custom_referer passed by caller / GUI / Chrome extension.
    2. Dynamic extraction from URL query parameters (?ref=, ?referer=, ?origin=, ?source=).
    3. Known cross-domain CDN mapping (where CDN host differs completely from landing site).
    4. Universal fallback to the URL's root origin (https://hostname/).
    """
    if custom_referer and custom_referer.strip():
        return custom_referer.strip()

    parsed = urlparse(url)
    if not parsed.netloc:
        return None

    # Check query string for embedded referer/origin parameters
    if parsed.query:
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        for key in ("referer", "ref", "origin", "source", "site", "from"):
            if key in qs and qs[key]:
                candidate = qs[key][0].strip()
                if candidate.startswith("http://") or candidate.startswith("https://"):
                    return candidate
                elif "." in candidate:
                    return f"https://{candidate.lstrip('/')}/"

    # Known cross-domain CDN signatures (where CDN domain has a different name from the portal)
    host = parsed.netloc.lower()
    known_cdn_signatures = {
        "uwucdn": "https://kwik.cx/",
        "kwik": "https://kwik.cx/",
        "animepahe": "https://animepahe.pw/",
        "pahe.win": "https://pahe.win/",
    }
    for sig, target_ref in known_cdn_signatures.items():
        if sig in host:
            return target_ref

    # Universal default: root origin of the URL itself
    return f"{parsed.scheme}://{parsed.netloc}/"


def _safe_output_path(dest_dir: str, filename: str) -> Path:
    """Resolve and create output directory; return full file path."""
    out = Path(dest_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out / filename


# ---------------------------------------------------------------------------
# Server Capability Probe
# ---------------------------------------------------------------------------

@dataclass
class ServerProbe:
    """Information gathered about the remote file and server capabilities."""
    supports_ranges: bool
    total_size: Optional[int]
    filename: Optional[str]
    status_code: int


def probe_server(
    url: str,
    headers: dict[str, str],
    impersonate: str = "chrome",
) -> ServerProbe:
    """
    Probe server with a Range: bytes=0-0 GET request to check:
    - Accept-Ranges / 206 Partial Content support
    - Total content length
    - Suggested filename from Content-Disposition
    - Expired link status (403, 410, 401)
    """
    from curl_cffi import requests as cffi_requests

    probe_headers = dict(headers)
    probe_headers["Range"] = "bytes=0-0"

    ref = infer_referer(url, probe_headers.get("Referer"))
    if ref:
        probe_headers.setdefault("Referer", ref)

    try:
        resp = cffi_requests.get(
            url,
            headers=probe_headers,
            impersonate=impersonate,
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            allow_redirects=True,
        )
    except Exception as exc:
        log.debug(f"Probe request failed: {exc}")
        raise

    status = resp.status_code
    resp_headers = resp.headers

    if status in (401, 403, 410):
        resp.close()
        raise _ExpiredURLError(f"HTTP {status}")

    supports_ranges = False
    total_size: Optional[int] = None
    suggested_filename = filename_from_headers(resp_headers)

    if status == 206:
        supports_ranges = True
        cr = resp_headers.get("Content-Range", "")
        if cr:
            # Format: "bytes 0-0/TOTAL"
            try:
                total_size = int(cr.rsplit("/", 1)[-1])
            except (ValueError, IndexError):
                pass
    elif status == 200:
        # Server ignored Range header
        cl = resp_headers.get("Content-Length")
        if cl:
            try:
                total_size = int(cl)
            except ValueError:
                pass
        # Check explicit Accept-Ranges
        ar = resp_headers.get("Accept-Ranges", "")
        if "bytes" in ar.lower():
            supports_ranges = True

    resp.close()
    return ServerProbe(
        supports_ranges=supports_ranges,
        total_size=total_size,
        filename=suggested_filename,
        status_code=status,
    )


# ---------------------------------------------------------------------------
# Multi-Connection Chunk Worker & Manager
# ---------------------------------------------------------------------------

def _download_chunk_worker(
    url: str,
    headers: dict[str, str],
    impersonate: str,
    chunk: ChunkState,
    max_retries: int,
    abort_event: threading.Event,
    progress: Optional[Progress],
    task_id: Optional[int],
    manifest: DownloadManifest,
    state_lock: threading.Lock,
    on_bytes_read: Optional[Callable[[int], None]] = None,
) -> None:
    """Worker thread downloading a specific byte-range chunk to a temporary file."""
    from curl_cffi import requests as cffi_requests

    chunk_path = Path(chunk.temp_file)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_on_disk = chunk_path.stat().st_size if chunk_path.exists() else 0
    chunk_needed = chunk.total_bytes

    if bytes_on_disk >= chunk_needed:
        chunk.completed = True
        chunk.downloaded_bytes = chunk_needed
        return

    chunk.downloaded_bytes = bytes_on_disk
    attempt = 0
    backoff = INITIAL_BACKOFF_SECS

    while attempt <= max_retries:
        if abort_event.is_set():
            return

        attempt += 1
        current_disk_bytes = chunk_path.stat().st_size if chunk_path.exists() else 0
        if current_disk_bytes >= chunk_needed:
            chunk.completed = True
            chunk.downloaded_bytes = chunk_needed
            return

        req_start = chunk.start_byte + current_disk_bytes
        req_end = chunk.end_byte

        req_headers = dict(headers)
        req_headers["Range"] = f"bytes={req_start}-{req_end}"

        ref = infer_referer(url, req_headers.get("Referer"))
        if ref:
            req_headers.setdefault("Referer", ref)

        try:
            resp = cffi_requests.get(
                url,
                headers=req_headers,
                impersonate=impersonate,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=True,
            )

            if resp.status_code in (401, 403, 410):
                resp.close()
                abort_event.set()
                with state_lock:
                    manifest.status = "paused_expired"
                    manifest.save()
                raise _ExpiredURLError(f"HTTP {resp.status_code}")

            if resp.status_code == 416:
                resp.close()
                chunk.completed = True
                chunk.downloaded_bytes = chunk_needed
                return

            if resp.status_code not in (200, 206):
                resp.close()
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.reason}")

            with open(chunk_path, "ab") as fh:
                for data in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if abort_event.is_set():
                        resp.close()
                        return
                    if not data:
                        continue
                    fh.write(data)
                    chunk.downloaded_bytes += len(data)
                    if progress and task_id is not None:
                        progress.update(task_id, advance=len(data))
                    if on_bytes_read:
                        on_bytes_read(len(data))

            resp.close()

            final_disk_bytes = chunk_path.stat().st_size if chunk_path.exists() else 0
            if final_disk_bytes >= chunk_needed:
                chunk.completed = True
                chunk.downloaded_bytes = chunk_needed
                return

        except _ExpiredURLError:
            raise
        except Exception as exc:
            if abort_event.is_set():
                return
            if attempt > max_retries:
                log.error(f"Chunk {chunk.index} failed after {max_retries} retries: {exc}")
                abort_event.set()
                raise

            sleep_for = min(backoff, MAX_BACKOFF_SECS)
            log.warning(
                f"Chunk {chunk.index} retry {attempt}/{max_retries} ({exc}). Waiting {sleep_for:.0f}s"
            )
            time.sleep(sleep_for)
            backoff *= 2


def _stitch_chunks(filepath: Path, manifest: DownloadManifest) -> None:
    """Stitch completed chunk temporary files into target file."""
    log.info(f"Stitching {len(manifest.chunks)} chunks into {filepath.name}...")
    console.print(f"[cyan]🔗 Stitching {len(manifest.chunks)} parallel chunks into final file...[/]")

    with open(filepath, "wb") as out_fh:
        for chunk in sorted(manifest.chunks, key=lambda c: c.index):
            c_path = Path(chunk.temp_file)
            if not c_path.exists():
                raise FileNotFoundError(f"Missing chunk file: {c_path}")
            with open(c_path, "rb") as in_fh:
                while True:
                    buf = in_fh.read(1024 * 1024 * 2)  # 2MB buffer
                    if not buf:
                        break
                    out_fh.write(buf)

    # Clean up chunk temporary files
    for chunk in manifest.chunks:
        try:
            c_path = Path(chunk.temp_file)
            if c_path.exists():
                c_path.unlink()
        except Exception as exc:
            log.debug(f"Could not remove temp chunk {chunk.temp_file}: {exc}")

    manifest.remove_meta()
    console.print(f"[bold green]✨ File assembly complete:[/] {filepath.name}")


def _download_multi_chunk(
    url: str,
    headers: dict[str, str],
    filepath: Path,
    total_size: int,
    num_connections: int,
    max_retries: int,
    impersonate: str,
    manifest: Optional[DownloadManifest] = None,
    progress_callback: Optional[Callable[[int, Optional[int], float, str], None]] = None,
    show_terminal_progress: bool = True,
    cancel_event: Optional[threading.Event] = None,
) -> DownloadResult:
    """Manage multi-connection parallel chunk download."""
    num_chunks = max(2, min(num_connections, 16))

    req_headers = dict(headers)
    ref = infer_referer(url, req_headers.get("Referer"))
    if ref:
        req_headers.setdefault("Referer", ref)

    # Initialize or resume manifest
    if manifest is None:
        meta_file = filepath.parent / f"{filepath.name}.meta.json"
        manifest = DownloadManifest.load(meta_file)

    if manifest is None or not manifest.is_chunked or len(manifest.chunks) != num_chunks:
        chunk_size = (total_size + num_chunks - 1) // num_chunks
        chunks: list[ChunkState] = []
        for i in range(num_chunks):
            start = i * chunk_size
            end = min(total_size - 1, (i + 1) * chunk_size - 1)
            temp_file = str(filepath.parent / f"{filepath.name}.part.chunk{i}")
            chunks.append(
                ChunkState(
                    index=i,
                    start_byte=start,
                    end_byte=end,
                    temp_file=temp_file,
                )
            )
        manifest = DownloadManifest(
            target_file=str(filepath),
            original_url=url,
            latest_url=url,
            total_bytes=total_size,
            supports_ranges=True,
            is_chunked=True,
            num_chunks=num_chunks,
            chunks=chunks,
            status="in_progress",
        )
        manifest.save()
    else:
        manifest.latest_url = url
        manifest.status = "in_progress"
        manifest.save()

    initial_completed_bytes = 0
    for chunk in manifest.chunks:
        c_path = Path(chunk.temp_file)
        if c_path.exists():
            disk_b = c_path.stat().st_size
            chunk.downloaded_bytes = min(disk_b, chunk.total_bytes)
            if chunk.downloaded_bytes >= chunk.total_bytes:
                chunk.completed = True
        else:
            chunk.downloaded_bytes = 0
        initial_completed_bytes += chunk.downloaded_bytes

    if initial_completed_bytes >= total_size:
        if progress_callback:
            progress_callback(total_size, total_size, 0.0, "Stitching chunks...")
        _stitch_chunks(filepath, manifest)
        if progress_callback:
            progress_callback(total_size, total_size, 0.0, "Complete")
        return DownloadResult(
            status=DownloadStatus.COMPLETED,
            path=filepath,
            bytes_downloaded=total_size,
            total_size=total_size,
            manifest=manifest,
        )

    if show_terminal_progress:
        console.print(
            f"[bold green]⚡ Multi-connection speed boost active:[/] "
            f"[cyan]{num_chunks} parallel connections[/] ({total_size / (1024*1024):.1f} MB)"
        )

    abort_event = threading.Event()
    state_lock = threading.Lock()

    current_downloaded = initial_completed_bytes
    last_tick_time = time.time()
    last_tick_bytes = initial_completed_bytes
    current_speed = 0.0

    def on_bytes_read(chunk_len: int):
        nonlocal current_downloaded, last_tick_time, last_tick_bytes, current_speed
        with state_lock:
            current_downloaded += chunk_len
            now = time.time()
            elapsed = now - last_tick_time
            if elapsed >= 0.2:
                delta = current_downloaded - last_tick_bytes
                current_speed = delta / elapsed
                last_tick_time = now
                last_tick_bytes = current_downloaded
                if progress_callback:
                    progress_callback(
                        current_downloaded,
                        total_size,
                        current_speed,
                        f"Downloading ({num_chunks} connections)...",
                    )

    expired_error_raised = False

    progress_columns = [
        TextColumn("[bold blue]{task.fields[filename]}"),
        BarColumn(bar_width=40),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ]

    def run_workers(progress_obj: Optional[Progress], t_id: Optional[int]):
        nonlocal expired_error_raised
        with ThreadPoolExecutor(max_workers=num_chunks) as executor:
            futures = [
                executor.submit(
                    _download_chunk_worker,
                    url=url,
                    headers=req_headers,
                    impersonate=impersonate,
                    chunk=chunk,
                    max_retries=max_retries,
                    abort_event=abort_event,
                    progress=progress_obj,
                    task_id=t_id,
                    manifest=manifest,
                    state_lock=state_lock,
                    on_bytes_read=on_bytes_read,
                )
                for chunk in manifest.chunks
            ]

            while any(not f.done() for f in futures):
                if cancel_event and cancel_event.is_set():
                    abort_event.set()
                time.sleep(0.05)

            for future in as_completed(futures):
                try:
                    future.result()
                except _ExpiredURLError:
                    expired_error_raised = True
                except Exception as exc:
                    log.error(f"Worker thread error: {exc}")

    if show_terminal_progress:
        with Progress(*progress_columns, transient=False) as progress:
            task_id = progress.add_task(
                "Downloading",
                filename=f"{filepath.name} (x{num_chunks})",
                total=total_size,
                completed=initial_completed_bytes,
            )
            run_workers(progress, task_id)
    else:
        run_workers(None, None)

    total_downloaded = sum(
        Path(c.temp_file).stat().st_size for c in manifest.chunks if Path(c.temp_file).exists()
    )
    manifest.downloaded_bytes = total_downloaded

    if cancel_event and cancel_event.is_set():
        manifest.status = "paused_cancelled"
        manifest.save()
        if progress_callback:
            progress_callback(total_downloaded, total_size, 0.0, "Paused")
        return DownloadResult(
            status=DownloadStatus.CANCELLED,
            path=filepath,
            bytes_downloaded=total_downloaded,
            total_size=total_size,
            manifest=manifest,
            error="Download cancelled by user",
        )

    if expired_error_raised or abort_event.is_set():
        manifest.status = "paused_expired"
        manifest.save()
        if progress_callback:
            progress_callback(total_downloaded, total_size, 0.0, "Link Expired (403)")
        return DownloadResult(
            status=DownloadStatus.EXPIRED_URL,
            path=filepath,
            bytes_downloaded=total_downloaded,
            total_size=total_size,
            manifest=manifest,
            error="HTTP 403/410 — signed URL expired or missing Referer",
        )

    all_done = all(
        Path(c.temp_file).exists() and Path(c.temp_file).stat().st_size >= c.total_bytes
        for c in manifest.chunks
    )

    if all_done:
        if progress_callback:
            progress_callback(total_size, total_size, 0.0, "Stitching chunks...")
        _stitch_chunks(filepath, manifest)
        if progress_callback:
            progress_callback(total_size, total_size, 0.0, "Complete")
        return DownloadResult(
            status=DownloadStatus.COMPLETED,
            path=filepath,
            bytes_downloaded=total_size,
            total_size=total_size,
            manifest=manifest,
        )
    else:
        manifest.status = "failed"
        manifest.save()
        if progress_callback:
            progress_callback(total_downloaded, total_size, 0.0, "Failed")
        return DownloadResult(
            status=DownloadStatus.FAILED,
            path=filepath,
            bytes_downloaded=total_downloaded,
            total_size=total_size,
            manifest=manifest,
            error="Download interrupted or incomplete",
        )


# ---------------------------------------------------------------------------
# Single-Connection Stream Downloader (Fallback & < 50MB)
# ---------------------------------------------------------------------------

def _download_single_stream(
    url: str,
    headers: dict[str, str],
    filepath: Path,
    max_retries: int,
    impersonate: str,
    probe: Optional[ServerProbe] = None,
    manifest: Optional[DownloadManifest] = None,
    progress_callback: Optional[Callable[[int, Optional[int], float, str], None]] = None,
    show_terminal_progress: bool = True,
    cancel_event: Optional[threading.Event] = None,
) -> DownloadResult:
    """Download using a single connection with byte-range resume and retries."""
    from curl_cffi import requests as cffi_requests

    existing_bytes = filepath.stat().st_size if filepath.exists() else 0

    req_headers = dict(headers)
    ref = infer_referer(url, req_headers.get("Referer"))
    if ref:
        req_headers.setdefault("Referer", ref)

    if manifest is None:
        meta_file = filepath.parent / f"{filepath.name}.meta.json"
        manifest = DownloadManifest.load(meta_file)

    if manifest is None:
        manifest = DownloadManifest(
            target_file=str(filepath),
            original_url=url,
            latest_url=url,
            total_bytes=probe.total_size if probe else None,
            downloaded_bytes=existing_bytes,
            supports_ranges=probe.supports_ranges if probe else True,
            is_chunked=False,
            status="in_progress",
        )
    else:
        manifest.latest_url = url
        manifest.status = "in_progress"

    manifest.save()

    attempt = 0
    backoff = INITIAL_BACKOFF_SECS

    while attempt <= max_retries:
        if cancel_event and cancel_event.is_set():
            manifest.status = "paused_cancelled"
            manifest.save()
            return DownloadResult(
                status=DownloadStatus.CANCELLED,
                path=filepath,
                bytes_downloaded=existing_bytes,
                total_size=manifest.total_bytes,
                manifest=manifest,
            )

        attempt += 1
        existing_bytes = filepath.stat().st_size if filepath.exists() else 0
        manifest.downloaded_bytes = existing_bytes

        stream_headers = dict(req_headers)
        if existing_bytes > 0 and manifest.supports_ranges:
            stream_headers["Range"] = f"bytes={existing_bytes}-"
            log.info(f"Resuming from byte {existing_bytes:,}")

        try:
            resp = cffi_requests.get(
                url,
                headers=stream_headers,
                impersonate=impersonate,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=True,
            )

            if resp.status_code in (401, 403, 410):
                resp.close()
                manifest.status = "paused_expired"
                manifest.save()
                if progress_callback:
                    progress_callback(existing_bytes, manifest.total_bytes, 0.0, "Link Expired (403)")
                return DownloadResult(
                    status=DownloadStatus.EXPIRED_URL,
                    path=filepath,
                    bytes_downloaded=existing_bytes,
                    total_size=manifest.total_bytes,
                    manifest=manifest,
                    error=f"HTTP {resp.status_code} — link expired or missing Referer",
                )

            if resp.status_code == 416:
                resp.close()
                manifest.remove_meta()
                if progress_callback:
                    progress_callback(existing_bytes, existing_bytes, 0.0, "Complete")
                return DownloadResult(
                    status=DownloadStatus.COMPLETED,
                    path=filepath,
                    bytes_downloaded=existing_bytes,
                    total_size=existing_bytes,
                    manifest=manifest,
                )

            if resp.status_code not in (200, 206):
                resp.close()
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.reason}")

            total_size = manifest.total_bytes
            cr = resp.headers.get("Content-Range", "")
            cl = resp.headers.get("Content-Length")

            if cr:
                try:
                    total_size = int(cr.rsplit("/", 1)[-1])
                except (ValueError, IndexError):
                    pass
            elif total_size is None and cl:
                try:
                    total_size = int(cl) + existing_bytes
                except ValueError:
                    pass

            manifest.total_bytes = total_size

            if resp.status_code == 200 and existing_bytes > 0:
                log.warning("Server ignored Range header (200). Restarting download.")
                existing_bytes = 0

            mode = "ab" if resp.status_code == 206 else "wb"
            bytes_written = existing_bytes

            progress_columns = [
                TextColumn("[bold blue]{task.fields[filename]}"),
                BarColumn(bar_width=40),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ]

            last_cb_time = time.time()
            last_cb_bytes = bytes_written

            def stream_data(progress_obj: Optional[Progress], t_id: Optional[int]):
                nonlocal bytes_written, last_cb_time, last_cb_bytes
                with open(filepath, mode) as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if cancel_event and cancel_event.is_set():
                            resp.close()
                            return
                        if not chunk:
                            continue
                        fh.write(chunk)
                        bytes_written += len(chunk)
                        if progress_obj and t_id is not None:
                            progress_obj.update(t_id, completed=bytes_written)

                        now = time.time()
                        if progress_callback and (now - last_cb_time >= 0.2):
                            spd = (bytes_written - last_cb_bytes) / (now - last_cb_time)
                            progress_callback(bytes_written, total_size, spd, "Downloading...")
                            last_cb_time = now
                            last_cb_bytes = bytes_written

            if show_terminal_progress:
                with Progress(*progress_columns, transient=False) as progress:
                    task_id = progress.add_task(
                        "Downloading",
                        filename=filepath.name,
                        total=total_size,
                        completed=existing_bytes,
                    )
                    stream_data(progress, task_id)
            else:
                stream_data(None, None)

            resp.close()

            if cancel_event and cancel_event.is_set():
                manifest.status = "paused_cancelled"
                manifest.downloaded_bytes = bytes_written
                manifest.save()
                return DownloadResult(
                    status=DownloadStatus.CANCELLED,
                    path=filepath,
                    bytes_downloaded=bytes_written,
                    total_size=total_size,
                    manifest=manifest,
                )

            manifest.downloaded_bytes = bytes_written
            manifest.remove_meta()
            if progress_callback:
                progress_callback(bytes_written, total_size or bytes_written, 0.0, "Complete")

            return DownloadResult(
                status=DownloadStatus.COMPLETED,
                path=filepath,
                bytes_downloaded=bytes_written,
                total_size=total_size or bytes_written,
                manifest=manifest,
            )

        except Exception as exc:
            if filepath.exists():
                existing_bytes = filepath.stat().st_size
                manifest.downloaded_bytes = existing_bytes
                manifest.save()

            if attempt > max_retries:
                manifest.status = "failed"
                manifest.save()
                return DownloadResult(
                    status=DownloadStatus.FAILED,
                    path=filepath,
                    bytes_downloaded=existing_bytes,
                    total_size=manifest.total_bytes,
                    manifest=manifest,
                    error=str(exc),
                )

            sleep_for = min(backoff, MAX_BACKOFF_SECS)
            log.warning(
                f"Attempt {attempt}/{max_retries} failed ({exc}). Retrying in {sleep_for:.0f}s..."
            )
            time.sleep(sleep_for)
            backoff *= 2


# ---------------------------------------------------------------------------
# Public Entry Point
# ---------------------------------------------------------------------------

def download(
    url: str,
    headers: dict[str, str],
    dest_dir: str = ".",
    filename: Optional[str] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    impersonate: str = "chrome",
    num_connections: int = DEFAULT_NUM_CONNECTIONS,
    min_chunk_size: int = MULTI_CHUNK_MIN_SIZE,
    progress_callback: Optional[Callable[[int, Optional[int], float, str], None]] = None,
    show_terminal_progress: bool = True,
    cancel_event: Optional[threading.Event] = None,
) -> DownloadResult:
    """
    Download *url* with Cloudflare impersonation, auto-resume, multi-connection
    chunking for >50MB files, and expired URL detection.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        log.error("curl_cffi is not installed. Run: pip install curl_cffi")
        return DownloadResult(
            status=DownloadStatus.FAILED,
            path=Path(dest_dir),
            error="curl_cffi is not installed",
        )

    req_headers = dict(headers)
    ref = infer_referer(url, req_headers.get("Referer"))
    if ref:
        req_headers.setdefault("Referer", ref)

    if filename is None:
        filename = filename_from_url(url)
    filepath = _safe_output_path(dest_dir, filename)

    # 1. Check for existing state manifest
    meta_path = filepath.parent / f"{filepath.name}.meta.json"
    manifest = DownloadManifest.load(meta_path)

    # 2. Probe server capabilities
    probe: Optional[ServerProbe] = None
    try:
        probe = probe_server(url, headers=req_headers, impersonate=impersonate)
        if probe.filename and filename == filename_from_url(url):
            filename = probe.filename
            filepath = _safe_output_path(dest_dir, filename)
    except _ExpiredURLError:
        log.warning("Probe detected expired URL (HTTP 401/403/410).")
        existing_bytes = filepath.stat().st_size if filepath.exists() else 0
        if manifest:
            manifest.status = "paused_expired"
            manifest.save()
        if progress_callback:
            progress_callback(existing_bytes, None, 0.0, "Link Expired (403)")
        return DownloadResult(
            status=DownloadStatus.EXPIRED_URL,
            path=filepath,
            bytes_downloaded=existing_bytes,
            manifest=manifest,
            error="HTTP 403/410 — signed URL expired or missing Referer",
        )
    except Exception as exc:
        log.debug(f"Server probe failed ({exc}) — proceeding with single-stream fallback.")

    # 3. Check if existing completed file already exists
    if probe and probe.total_size:
        if filepath.exists() and filepath.stat().st_size == probe.total_size:
            log.info(f"File {filepath.name} is already completely downloaded.")
            if manifest:
                manifest.remove_meta()
            if progress_callback:
                progress_callback(probe.total_size, probe.total_size, 0.0, "Complete")
            return DownloadResult(
                status=DownloadStatus.COMPLETED,
                path=filepath,
                bytes_downloaded=probe.total_size,
                total_size=probe.total_size,
                manifest=manifest,
            )

    # 4. Determine execution strategy: Multi-connection Chunking vs Single-stream
    use_multi_connection = False
    if probe and probe.supports_ranges and probe.total_size:
        if probe.total_size >= min_chunk_size:
            use_multi_connection = True

    if manifest and manifest.is_chunked:
        use_multi_connection = True

    if use_multi_connection and probe and probe.total_size:
        return _download_multi_chunk(
            url=url,
            headers=req_headers,
            filepath=filepath,
            total_size=probe.total_size,
            num_connections=num_connections,
            max_retries=max_retries,
            impersonate=impersonate,
            manifest=manifest,
            progress_callback=progress_callback,
            show_terminal_progress=show_terminal_progress,
            cancel_event=cancel_event,
        )
    else:
        return _download_single_stream(
            url=url,
            headers=req_headers,
            filepath=filepath,
            max_retries=max_retries,
            impersonate=impersonate,
            probe=probe,
            manifest=manifest,
            progress_callback=progress_callback,
            show_terminal_progress=show_terminal_progress,
            cancel_event=cancel_event,
        )
