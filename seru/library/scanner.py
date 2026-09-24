"""Headless filesystem scanner for Seru's rebuildable index."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
from ..database.repository import LibraryRepository
from ..media.ffprobe import MediaMetadata, probe_media
from .parser import VIDEO_EXTENSIONS, is_season_folder, parse_media_file

@dataclass
class ScanResult:
    scanned: int = 0
    probed: int = 0
    reused_metadata: int = 0
    errors: int = 0
    stale_removed: int = 0

def title_key(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().casefold()

class LibraryScanner:
    def __init__(self, repository: LibraryRepository, library_root: Path, location_id: str = "default") -> None:
        self.repository, self.library_root, self.location_id = repository, library_root.resolve(), location_id
    def scan(self) -> ScanResult:
        if not self.library_root.is_dir(): raise ValueError(f"Library root is not a directory: {self.library_root}")
        result, seen_paths = ScanResult(), set()
        self.repository.begin_scan(self.location_id, self.library_root)
        try:
            for file_path in self.library_root.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
                    self._scan_file(file_path, self._anime_dir_for(file_path), seen_paths, result)
        except (OSError, PermissionError) as error:
            result.errors += 1
            print(f"Warning: could not walk {self.library_root}: {error}")
        result.stale_removed = self.repository.remove_stale_files(self.location_id, seen_paths)
        self.repository.commit()
        return result
    def _scan_file(self, file_path: Path, anime_dir: Path, seen_paths: set[str], result: ScanResult) -> None:
        try:
            relative_path, file_stat = file_path.relative_to(self.library_root).as_posix(), file_path.stat()
            seen_paths.add(relative_path)
            parsed = parse_media_file(file_path, anime_dir)
            existing = self.repository.existing_file(self.location_id, relative_path)
            unchanged = existing is not None and existing["file_size"] == file_stat.st_size and existing["modified_ns"] == file_stat.st_mtime_ns
            metadata, probe_error = None, None
            if unchanged and existing["probe_status"] in {"ok", "failed"}:
                result.reused_metadata += 1
                metadata = MediaMetadata(existing["video_codec"], existing["audio_codec"], existing["width"], existing["height"], existing["duration_seconds"])
                probe_status, probe_error = existing["probe_status"], existing["probe_error"]
            else:
                try:
                    metadata, probe_status = probe_media(file_path), "ok"
                    result.probed += 1
                except Exception as error:  # One malformed file must not stop a scan.
                    probe_status, probe_error = "failed", str(error)
                    result.errors += 1
                    print(f"Warning: could not probe {file_path}: {error}")
            self.repository.save_file(self.location_id, relative_path, title=parsed.title, title_key=title_key(parsed.title), season_number=parsed.season_number, episode_number=parsed.episode_number, is_movie=parsed.is_movie, needs_review=parsed.needs_review, review_reason=parsed.review_reason, file_size=file_stat.st_size, modified_ns=file_stat.st_mtime_ns, metadata=metadata, probe_status=probe_status, probe_error=probe_error)
            result.scanned += 1
        except Exception as error:  # Stat/parse/database failures are isolated per file too.
            result.errors += 1
            print(f"Warning: could not index {file_path}: {error}")

    def _anime_dir_for(self, file_path: Path) -> Path:
        """Find the show folder below organizational buckets in this library layout."""
        for parent in file_path.parents:
            if parent == self.library_root:
                break
            if is_season_folder(parent.name) and parent.parent != self.library_root:
                return parent.parent
        return file_path.parent
