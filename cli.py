"""
Smart Download Manager — cli.py

Interactive command-line interface.
  • Main menu with new download & "Update URL for existing file" options
  • Auto-discovers browser cookies (cf_clearance) for Cloudflare bypass
  • Background extension bridge listener on port 8992
  • Multi-connection speed boosting for large files (>50MB)
  • Seamless link refreshing on HTTP 403 / 410 with partial file verification
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import browser_session
from bridge_server import BridgeServer, DEFAULT_BRIDGE_PORT
from browser_session import BrowserSession, get_browser_session, make_session_headers
from downloader import (
    DEFAULT_NUM_CONNECTIONS,
    MULTI_CHUNK_MIN_SIZE,
    DownloadResult,
    DownloadStatus,
    download,
    filename_from_url,
)
from state import DownloadManifest, find_unfinished_downloads
from queue_manager import (
    BatchSummary,
    QueueItem,
    QueueItemStatus,
    QueueManager,
    parse_urls_file,
)
from torrent_engine import (
    download_torrent,
    is_torrent_source,
    parse_magnet_display_name,
)

log = logging.getLogger(__name__)
console = Console()

DEFAULT_DOWNLOAD_DIR = str(Path.cwd() / "downloads")


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------

def _banner() -> None:
    banner_text = Text.assemble(
        ("╔════════════════════════════════════════════════════════╗\n", "bold cyan"),
        ("║         ⬇  Smart Download Manager  v0.3              ║\n", "bold cyan"),
        ("║  Cloudflare-ready · Multi-Connection · Extension Bridge║\n", "dim cyan"),
        ("╚════════════════════════════════════════════════════════╝", "bold cyan"),
    )
    console.print(banner_text)


def _print_session_info(session: BrowserSession | None, url: str) -> None:
    """Show the user what browser cookies we found (or didn't)."""
    if session is None:
        console.print(
            "[yellow]⚠  No active cookies found for this domain.[/]\n"
            "   Proceeding without Cloudflare session cookies.\n"
            "   (Tip: Open the site in Chrome and click the extension icon to send cookies!)\n"
        )
        return

    cf = "[bold green]✅ cf_clearance[/]" if session.has_cf_clearance else "[yellow]❌ cf_clearance not found[/]"
    panel = Panel(
        f"Source     :  [bold]{session.browser_name.title()}[/]\n"
        f"Cookies    :  {len(session.cookies)} loaded  ({cf})\n"
        f"User-Agent :  [dim]{session.user_agent[:72]}…[/]",
        title="[bold green]Browser Session Loaded[/]",
        border_style="green",
    )
    console.print(panel)


def _print_result(result: DownloadResult) -> None:
    """Pretty-print the download outcome."""
    if result.status == DownloadStatus.COMPLETED:
        console.print(
            f"\n[bold green]✅ Download complete![/]  "
            f"Saved to [bold]{result.path}[/]  "
            f"({result.bytes_downloaded:,} bytes)\n"
        )
    elif result.status == DownloadStatus.EXPIRED_URL:
        console.print(
            f"\n[bold yellow]⏳ Link expired (HTTP 401/403/410).[/]  "
            f"Partial file safe at [bold]{result.path}[/]  "
            f"({result.bytes_downloaded:,} bytes saved so far)\n"
        )
    else:
        console.print(
            f"\n[bold red]❌ Download failed:[/]  {result.error}\n"
            f"   Partial file (if any) at [bold]{result.path}[/]\n"
        )


# ---------------------------------------------------------------------------
# Link Refreshing Mechanism
# ---------------------------------------------------------------------------

def _handle_expired(
    result: DownloadResult,
    num_connections: int = DEFAULT_NUM_CONNECTIONS,
    min_chunk_size: int = MULTI_CHUNK_MIN_SIZE,
) -> None:
    """
    Prompt for a fresh URL when a signed link expires, re-fetch cookies,
    verify existing bytes on disk, and resume.
    """
    while True:
        try:
            console.print("[bold yellow]Link expired. Paste a fresh URL to resume (or press Enter to skip):[/] ", end="")
            fresh_url = input().strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Skipped. Download state saved.[/]")
            return

        if not fresh_url or fresh_url.lower() in ("s", "skip"):
            console.print("[dim]Download paused. State saved — you can resume anytime.[/]\n")
            return

        # Re-fetch fresh browser cookies for the new domain
        parsed = urlparse(fresh_url)
        console.print(f"\n[cyan]🔍 Re-fetching fresh browser session for {parsed.netloc} …[/]")
        new_session = get_browser_session(fresh_url)
        _print_session_info(new_session, fresh_url)
        new_headers = make_session_headers(new_session)

        # Verify existing file/chunk bytes on disk
        target_path = result.path
        existing_bytes = 0
        if target_path.exists():
            existing_bytes = target_path.stat().st_size
        else:
            chunk_files = list(target_path.parent.glob(f"{target_path.name}.part.chunk*"))
            if chunk_files:
                existing_bytes = sum(c.stat().st_size for c in chunk_files)

        console.print(
            f"[bold green]✔ Verified partial file on disk:[/] [bold]{target_path.name}[/] "
            f"([cyan]{existing_bytes:,}[/] bytes existing)"
        )
        console.print("[cyan]Resuming remaining bytes with fresh URL …[/]\n")

        new_result = download(
            url=fresh_url,
            headers=new_headers,
            dest_dir=str(target_path.parent),
            filename=target_path.name,
            num_connections=num_connections,
            min_chunk_size=min_chunk_size,
        )
        _print_result(new_result)

        if new_result.status == DownloadStatus.EXPIRED_URL:
            continue
        return


def _update_url_for_existing(
    dest_dir: str,
    num_connections: int = DEFAULT_NUM_CONNECTIONS,
    min_chunk_size: int = MULTI_CHUNK_MIN_SIZE,
    preset_file: Optional[str] = None,
) -> None:
    """
    Manually point a fresh URL at an unfinished file on disk.
    """
    console.print("\n[bold cyan]─── Update URL for Unfinished Download ───[/]")

    target_path: Optional[Path] = None

    if preset_file:
        p = Path(preset_file).resolve()
        if p.exists() or p.parent.exists():
            target_path = p
    else:
        unfinished = find_unfinished_downloads(dest_dir)
        table = Table(title="Unfinished Downloads Detected", show_header=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Filename", style="bold")
        table.add_column("Downloaded", justify="right")
        table.add_column("Status", style="yellow")

        for idx, item in enumerate(unfinished, 1):
            t_name = Path(item.target_file).name
            size_str = f"{item.downloaded_bytes / (1024*1024):.1f} MB"
            if item.total_bytes:
                size_str += f" / {item.total_bytes / (1024*1024):.1f} MB"
            table.add_row(str(idx), t_name, size_str, item.status)

        if unfinished:
            console.print(table)
            console.print(
                "Select a file number from above, enter [bold]C[/] to specify a custom path, "
                "or [bold]B[/] to go back:"
            )
            choice = input("  ➤  ").strip()
            if choice.lower() in ("b", "back", ""):
                return
            if choice.isdigit() and 1 <= int(choice) <= len(unfinished):
                target_path = Path(unfinished[int(choice) - 1].target_file)
            elif choice.lower() == "c":
                console.print("Enter full path or filename of unfinished file:")
                custom = input("  ➤  ").strip()
                if not custom:
                    return
                target_path = Path(custom).resolve()
            else:
                return
        else:
            console.print("[dim]No unfinished tasks found in downloads directory.[/]")
            console.print("Enter the path or filename of the unfinished file (or press Enter to cancel):")
            custom = input("  ➤  ").strip()
            if not custom:
                return
            target_path = Path(dest_dir).resolve() / custom if not Path(custom).is_absolute() else Path(custom)

    if target_path is None:
        return

    current_size = 0
    if target_path.exists():
        current_size = target_path.stat().st_size
    else:
        chunks = list(target_path.parent.glob(f"{target_path.name}.part.chunk*"))
        if chunks:
            current_size = sum(c.stat().st_size for c in chunks)

    console.print(
        f"\n[bold]Selected File:[/] {target_path}\n"
        f"[bold]Bytes on Disk:[/] {current_size:,} bytes "
        f"({current_size / (1024*1024):.2f} MB)"
    )

    console.print("[bold]Paste the fresh download URL (or press Enter to cancel):[/]")
    try:
        fresh_url = input("  ➤  ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not fresh_url:
        console.print("[dim]Cancelled.[/]")
        return

    parsed = urlparse(fresh_url)
    console.print(f"\n[cyan]🔍 Harvesting session cookies for {parsed.netloc} …[/]")
    session = get_browser_session(fresh_url)
    _print_session_info(session, fresh_url)
    headers = make_session_headers(session)

    console.print(f"[cyan]Resuming download for {target_path.name} …[/]\n")
    result = download(
        url=fresh_url,
        headers=headers,
        dest_dir=str(target_path.parent),
        filename=target_path.name,
        num_connections=num_connections,
        min_chunk_size=min_chunk_size,
    )
    _print_result(result)

    if result.status == DownloadStatus.EXPIRED_URL:
        _handle_expired(result, num_connections=num_connections, min_chunk_size=min_chunk_size)


# ---------------------------------------------------------------------------
# Batch File Execution (Sprint 4)
# ---------------------------------------------------------------------------

def run_batch_cli(
    file_path: str | Path,
    dest_dir: str = DEFAULT_DOWNLOAD_DIR,
    max_concurrent: int = 2,
    num_connections: int = DEFAULT_NUM_CONNECTIONS,
    min_chunk_size: int = MULTI_CHUNK_MIN_SIZE,
) -> Optional[BatchSummary]:
    """
    Execute batch downloads from a URLs text file with background queue processing,
    concurrency management, live progress bars, and a final summary report.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        console.print(f"[bold red]❌ Batch file not found:[/] {path}")
        return None

    try:
        items = parse_urls_file(path, default_dest=dest_dir)
    except Exception as exc:
        console.print(f"[bold red]❌ Error parsing batch file:[/] {exc}")
        return None

    if not items:
        console.print(f"[yellow]⚠ No valid URLs found in {path.name}[/]")
        return None

    bridge = BridgeServer(port=DEFAULT_BRIDGE_PORT)
    bridge_ok = bridge.start()

    _banner()
    if bridge_ok:
        console.print(f"[dim green]✔ Chrome Extension Bridge listening on http://127.0.0.1:{DEFAULT_BRIDGE_PORT}[/]\n")

    console.print(
        f"[bold cyan]📋 Ingested {len(items)} download tasks from:[/] [bold]{path.name}[/]\n"
        f"[dim]Concurrency limit: {max_concurrent} active downloads · Target folder: {dest_dir}[/]\n"
    )

    # Show initial items preview table
    table = Table(title="Batch Ingestion Manifest", show_header=True)
    table.add_column("#", width=4, justify="right")
    table.add_column("Filename / Target", style="bold", min_width=20)
    table.add_column("Referer", style="dim", min_width=20)
    table.add_column("URL", style="dim", max_width=40)

    for idx, it in enumerate(items, 1):
        ref_display = it.referer or "(auto-inferred)"
        url_display = it.url[:38] + "…" if len(it.url) > 40 else it.url
        table.add_row(str(idx), it.display_name, ref_display, url_display)
    console.print(table)
    console.print("\n[bold green]🚀 Launching Background Queue Engine...[/]\n")

    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )

    queue = QueueManager(
        dest_dir=dest_dir,
        max_concurrent=max_concurrent,
        num_connections=num_connections,
        min_chunk_size=min_chunk_size,
    )
    for it in items:
        queue.add_item(
            url=it.url,
            filename=it.filename,
            referer=it.referer,
            dest_dir=dest_dir,
        )

    task_map: dict[str, int] = {}
    completed_event = threading.Event()

    def on_queue_done(summary: BatchSummary):
        completed_event.set()

    queue.on_queue_completed = on_queue_done

    progress_columns = [
        TextColumn("[bold blue]{task.fields[name]}"),
        BarColumn(bar_width=30),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        TextColumn("[yellow]{task.fields[status]}"),
    ]

    with Progress(*progress_columns, console=console, transient=False) as progress:
        overall_task = progress.add_task(
            "Batch Progress",
            total=len(items),
            completed=0,
            name="[bold magenta]Overall Batch[/]",
            status="Running",
        )

        def on_item_update(it: QueueItem):
            if it.status == QueueItemStatus.ACTIVE:
                if it.id not in task_map:
                    tid = progress.add_task(
                        "Download",
                        total=it.total_bytes,
                        completed=it.downloaded_bytes,
                        name=f"⚡ {it.display_name[:24]}",
                        status=it.status_msg,
                    )
                    task_map[it.id] = tid
                else:
                    tid = task_map[it.id]
                    st_msg = it.status_msg
                    if it.is_torrent_task and (it.peers > 0 or it.seeds > 0):
                        st_msg = f"{it.formatted_speed} · {it.peers}P/{it.seeds}S"
                    progress.update(
                        tid,
                        total=it.total_bytes,
                        completed=it.downloaded_bytes,
                        status=st_msg,
                    )

        def on_item_complete(it: QueueItem):
            if it.id in task_map:
                tid = task_map[it.id]
                if it.status == QueueItemStatus.COMPLETED:
                    cmpl_label = "[green]Done (Torrent)[/]" if it.is_torrent_task else "[green]Done[/]"
                    progress.update(tid, completed=it.total_bytes or it.downloaded_bytes, status=cmpl_label)
                elif it.status == QueueItemStatus.SKIPPED:
                    progress.update(tid, status="[cyan]Skipped[/]")
                elif it.status == QueueItemStatus.EXPIRED:
                    progress.update(tid, status="[yellow]Expired (403)[/]")
                elif it.status == QueueItemStatus.FAILED:
                    progress.update(tid, status="[red]Failed[/]")
            # Advance overall progress
            completed_count = sum(
                1 for x in queue.items
                if x.status in (
                    QueueItemStatus.COMPLETED,
                    QueueItemStatus.SKIPPED,
                    QueueItemStatus.EXPIRED,
                    QueueItemStatus.FAILED,
                    QueueItemStatus.CANCELLED,
                )
            )
            progress.update(overall_task, completed=completed_count)

        queue.on_item_updated = on_item_update
        queue.on_item_completed = on_item_complete

        queue.start()

        # Wait until all queue items are processed or interrupted
        try:
            while not completed_event.is_set():
                time.sleep(0.2)
        except (KeyboardInterrupt, SystemExit):
            console.print("\n[bold yellow]Batch download interrupted by user! Pausing queue...[/]")
            queue.stop()

    summary = queue.get_summary()
    summary.print_report(console)
    bridge.stop()
    return summary


# ---------------------------------------------------------------------------
# Interactive Menu Loop
# ---------------------------------------------------------------------------

def run_cli(
    dest_dir: str = DEFAULT_DOWNLOAD_DIR,
    initial_url: Optional[str] = None,
    num_connections: int = DEFAULT_NUM_CONNECTIONS,
    min_chunk_size: int = MULTI_CHUNK_MIN_SIZE,
    update_file: Optional[str] = None,
    batch_file: Optional[str] = None,
    max_concurrent: int = 2,
) -> None:
    """Main interactive CLI runner."""
    if batch_file:
        run_batch_cli(
            file_path=batch_file,
            dest_dir=dest_dir,
            max_concurrent=max_concurrent,
            num_connections=num_connections,
            min_chunk_size=min_chunk_size,
        )
        return

    # Start the extension bridge in background
    bridge = BridgeServer(port=DEFAULT_BRIDGE_PORT)
    bridge_ok = bridge.start()

    _banner()
    if bridge_ok:
        console.print(f"[dim green]✔ Chrome Extension Bridge listening on http://127.0.0.1:{DEFAULT_BRIDGE_PORT}[/]\n")

    try:
        if update_file:
            _update_url_for_existing(
                dest_dir=dest_dir,
                num_connections=num_connections,
                min_chunk_size=min_chunk_size,
                preset_file=update_file,
            )
            return

        if initial_url:
            if is_torrent_source(initial_url):
                console.print(f"\n[cyan]🧲 BitTorrent source detected:[/] [bold]{initial_url[:64]}[/]")
                console.print(f"[cyan]   To folder :[/]  {dest_dir}\n")
                res = download_torrent(
                    source=initial_url,
                    dest_dir=dest_dir,
                    show_terminal_progress=True,
                )
                _print_result(res)
                return

            console.print(f"[cyan]🔍 Scanning browsers for session cookies …[/]")
            session = get_browser_session(initial_url)
            _print_session_info(session, initial_url)
            headers = make_session_headers(session)

            filename = filename_from_url(initial_url)
            console.print(
                f"[cyan]⬇  Downloading:[/]  [bold]{filename}[/]\n"
                f"[cyan]   To folder :[/]  {dest_dir}\n"
            )
            res = download(
                url=initial_url,
                headers=headers,
                dest_dir=dest_dir,
                num_connections=num_connections,
                min_chunk_size=min_chunk_size,
            )
            _print_result(res)
            if res.status == DownloadStatus.EXPIRED_URL:
                _handle_expired(res, num_connections=num_connections, min_chunk_size=min_chunk_size)
            return

        while True:
            console.print("\n[bold]Select an option:[/]")
            console.print("  [bold green]1.[/] Download a single URL / Magnet link / .torrent")
            console.print("  [bold cyan]2.[/] Batch download from file (urls.txt)")
            console.print("  [bold magenta]3.[/] Update URL for existing file (Resume unfinished)")
            console.print("  [bold red]4.[/] Exit (or q)")

            try:
                choice = input("\n  ➤ Choice [1]: ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye! 👋[/]")
                break

            if choice in ("4", "q", "quit", "exit"):
                console.print("[dim]Goodbye! 👋[/]")
                break

            if choice == "2":
                console.print("\nEnter path to URLs file [urls.txt]: ", end="")
                try:
                    f_input = input().strip() or "urls.txt"
                except (EOFError, KeyboardInterrupt):
                    continue
                console.print("Enter maximum concurrent downloads [2]: ", end="")
                try:
                    c_input = input().strip() or str(max_concurrent)
                    conc = int(c_input)
                except (ValueError, EOFError, KeyboardInterrupt):
                    conc = 2
                run_batch_cli(
                    file_path=f_input,
                    dest_dir=dest_dir,
                    max_concurrent=conc,
                    num_connections=num_connections,
                    min_chunk_size=min_chunk_size,
                )
                continue

            if choice == "3":
                _update_url_for_existing(
                    dest_dir=dest_dir,
                    num_connections=num_connections,
                    min_chunk_size=min_chunk_size,
                )
                continue

            console.print("\n[bold]Enter download URL, magnet URI, or .torrent path[/] (or press Enter to go back):")
            try:
                url = input("  ➤  ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not url:
                continue

            if is_torrent_source(url):
                console.print(f"\n[cyan]🧲 BitTorrent source detected:[/] [bold]{url[:64]}[/]")
                console.print(f"[cyan]   Destination:[/] {dest_dir}\n")
                result = download_torrent(
                    source=url,
                    dest_dir=dest_dir,
                    show_terminal_progress=True,
                )
                _print_result(result)
                console.print("─" * 56)
                continue

            console.print(f"\n[cyan]🔍 Scanning browsers for session cookies …[/]")
            session = get_browser_session(url)
            _print_session_info(session, url)

            headers = make_session_headers(session)
            filename = filename_from_url(url)

            console.print(
                f"[cyan]⬇  Starting:[/]  [bold]{filename}[/]\n"
                f"[cyan]   Destination:[/]  {dest_dir}\n"
            )

            result = download(
                url=url,
                headers=headers,
                dest_dir=dest_dir,
                num_connections=num_connections,
                min_chunk_size=min_chunk_size,
            )
            _print_result(result)

            if result.status == DownloadStatus.EXPIRED_URL:
                _handle_expired(
                    result,
                    num_connections=num_connections,
                    min_chunk_size=min_chunk_size,
                )

            console.print("─" * 56)

    finally:
        bridge.stop()
