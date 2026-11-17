"""
Smart Download Manager — state.py

Download manifest and state persistence for resilient downloads.
Tracks metadata, partial bytes, and multi-connection chunk progress.
Enables link refreshing and resuming across process restarts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class ChunkState:
    """Tracks state and byte boundaries for an individual chunk."""
    index: int
    start_byte: int
    end_byte: int
    temp_file: str
    completed: bool = False
    downloaded_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.end_byte - self.start_byte + 1


@dataclass
class DownloadManifest:
    """Full state manifest for a file download task."""
    target_file: str
    original_url: str
    latest_url: str
    total_bytes: Optional[int] = None
    downloaded_bytes: int = 0
    supports_ranges: bool = True
    is_chunked: bool = False
    num_chunks: int = 1
    chunks: list[ChunkState] = field(default_factory=list)
    status: str = "in_progress"  # in_progress, paused_expired, completed, failed

    def meta_path(self) -> Path:
        """The path to the .meta.json file on disk."""
        target = Path(self.target_file)
        return target.parent / f"{target.name}.meta.json"

    def save(self) -> None:
        """Persist state to disk safely (write to temp then rename)."""
        meta_file = self.meta_path()
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)

        temp_file = meta_file.with_suffix(".json.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(meta_file)
        except Exception as exc:
            log.warning(f"Failed to save download manifest {meta_file}: {exc}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    @classmethod
    def load(cls, meta_path: Path | str) -> Optional[DownloadManifest]:
        """Load manifest from a .meta.json file."""
        path = Path(meta_path)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            chunks = [ChunkState(**c) for c in data.get("chunks", [])]
            return cls(
                target_file=data["target_file"],
                original_url=data["original_url"],
                latest_url=data.get("latest_url", data["original_url"]),
                total_bytes=data.get("total_bytes"),
                downloaded_bytes=data.get("downloaded_bytes", 0),
                supports_ranges=data.get("supports_ranges", True),
                is_chunked=data.get("is_chunked", False),
                num_chunks=data.get("num_chunks", 1),
                chunks=chunks,
                status=data.get("status", "in_progress"),
            )
        except Exception as exc:
            log.warning(f"Failed to read download manifest {path}: {exc}")
            return None

    def remove_meta(self) -> None:
        """Clean up the manifest file once download is fully completed."""
        meta_file = self.meta_path()
        if meta_file.exists():
            try:
                meta_file.unlink()
            except Exception as exc:
                log.debug(f"Could not remove meta file {meta_file}: {exc}")


def find_unfinished_downloads(dest_dir: str | Path) -> list[DownloadManifest]:
    """
    Scan dest_dir for unfinished downloads (.meta.json or partial files).
    Returns list of DownloadManifest objects.
    """
    directory = Path(dest_dir).resolve()
    if not directory.exists():
        return []

    manifests: list[DownloadManifest] = []
    seen_targets: set[Path] = set()

    # 1. Scan for explicit .meta.json files
    for meta_file in directory.glob("*.meta.json"):
        manifest = DownloadManifest.load(meta_file)
        if manifest:
            target = Path(manifest.target_file).resolve()
            manifests.append(manifest)
            seen_targets.add(target)

    # 2. Scan for leftover .part or files with partial chunks
    for chunk_file in directory.glob("*.part.chunk0"):
        # Target is filename before .part.chunk0
        stem = chunk_file.name[:-12]  # strip '.part.chunk0'
        target = directory / stem
        if target not in seen_targets:
            manifest = DownloadManifest(
                target_file=str(target),
                original_url="",
                latest_url="",
                status="paused_expired",
                is_chunked=True,
            )
            manifests.append(manifest)
            seen_targets.add(target)

    return manifests

