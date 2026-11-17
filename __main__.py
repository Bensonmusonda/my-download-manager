"""
Smart Download Manager — __main__.py

Entry point. Run with:
    python -m my_smart_downloader
  or:
    python __main__.py [URL] [-d DEST] [-c CONNECTIONS] [--gui]
"""

import argparse
import logging
import sys

# On Windows, attach to parent terminal console if run from CLI (so --help and CLI mode print output)
if sys.platform == "win32":
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    except Exception:
        pass

from cli import run_cli
from downloader import DEFAULT_NUM_CONNECTIONS, MULTI_CHUNK_MIN_SIZE


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart Download Manager — Cloudflare-ready, multi-connection, auto-resume CLI & Desktop Downloader",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Download URL (optional; opens interactive menu or GUI if omitted)",
    )
    parser.add_argument(
        "-g", "--gui",
        action="store_true",
        help="Launch the modern CustomTkinter desktop GUI window (default when no arguments provided)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Launch the interactive terminal CLI menu instead of Desktop GUI",
    )
    parser.add_argument(
        "-d", "--dest",
        default="downloads",
        help="Download destination directory (default: ./downloads)",
    )
    parser.add_argument(
        "-c", "--connections",
        type=int,
        default=DEFAULT_NUM_CONNECTIONS,
        help=f"Number of parallel connections for large files (default: {DEFAULT_NUM_CONNECTIONS})",
    )
    parser.add_argument(
        "-m", "--min-chunk-size",
        type=int,
        default=50,
        help="Minimum file size in MB to enable multi-connection chunking (default: 50)",
    )
    parser.add_argument(
        "-f", "--file",
        default=None,
        metavar="URLS_FILE",
        help="Batch download URLs from a text file (one URL per line, with optional | filename | referer)",
    )
    parser.add_argument(
        "-q", "--concurrent",
        type=int,
        default=2,
        help="Maximum concurrent active downloads in queue (default: 2)",
    )
    parser.add_argument(
        "-u", "--update-url",
        default=None,
        metavar="FILEPATH",
        help="Point a fresh URL at an unfinished file on disk",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose / debug logging",
    )
    args = parser.parse_args()

    # ── Configure logging ─────────────────────────────────────────────
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.cli:
        run_cli(
            dest_dir=args.dest,
            initial_url=args.url,
            num_connections=args.connections,
            min_chunk_size=args.min_chunk_size * 1024 * 1024,
            update_file=args.update_url,
            batch_file=args.file,
            max_concurrent=args.concurrent,
        )
    elif args.file:
        from cli import run_batch_cli
        run_batch_cli(
            file_path=args.file,
            dest_dir=args.dest,
            max_concurrent=args.concurrent,
            num_connections=args.connections,
            min_chunk_size=args.min_chunk_size * 1024 * 1024,
        )
    elif args.url or args.update_url:
        run_cli(
            dest_dir=args.dest,
            initial_url=args.url,
            num_connections=args.connections,
            min_chunk_size=args.min_chunk_size * 1024 * 1024,
            update_file=args.update_url,
            batch_file=args.file,
            max_concurrent=args.concurrent,
        )
    else:
        # Default: Launch modern Desktop GUI
        from gui import run_gui
        run_gui(default_dest=args.dest, initial_batch_file=args.file)


if __name__ == "__main__":
    main()
