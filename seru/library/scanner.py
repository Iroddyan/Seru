"""Headless filesystem scanner for Seru's rebuildable index."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import os
from ..database.repository import LibraryRepository
from ..media.ffprobe import MediaMetadata, probe_media
from .parser import ParsedMedia, VIDEO_EXTENSIONS, parse_loose_media_file, parse_media_file

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
    def __init__(self, repository: LibraryRepository, library_root: Path, location_id: str = "default",
                 library_type: str = "anime", probe_metadata: bool = True) -> None:
        self.repository, self.library_root, self.location_id = repository, library_root.resolve(), location_id
        self.library_type = library_type
        self.probe_metadata = probe_metadata
    def scan(self) -> ScanResult:
        if not self.library_root.is_dir(): raise ValueError(f"Library root is not a directory: {self.library_root}")
        result, seen_paths = ScanResult(), set()
        self.repository.begin_scan(self.location_id, self.library_root, self.library_type)
        walk_errors: list[OSError] = []
        try:
            for file_path in self._media_files(walk_errors.append):
                try:
                    title_dir = self._title_directory(file_path)
                    self._scan_file(file_path, title_dir, seen_paths, result,
                                    is_loose_file=self._is_loose_file(file_path, title_dir))
                except Exception as error:
                    walk_errors.append(OSError(str(error)))
        except (OSError, PermissionError) as error:
            walk_errors.append(error)
            print(f"Warning: could not walk {self.library_root}: {error}")
        result.errors += len(walk_errors)
        # An incomplete walk must never make indexed media appear deleted.
        if not walk_errors:
            result.stale_removed = self.repository.remove_stale_files(self.location_id, seen_paths)
        self.repository.commit()
        return result

    def refresh_paths(self, paths: set[Path]) -> ScanResult:
        """Refresh only notified files/directories after a debounced change batch."""
        if not self.library_root.is_dir():
            raise ValueError(f"Library root is not available: {self.library_root}")
        self.repository.begin_scan(self.location_id, self.library_root, self.library_type)
        result, seen = ScanResult(), set()
        for changed in sorted(paths, key=lambda path: not path.exists()):
            try:
                changed = changed.resolve(strict=False)
                if not changed.is_relative_to(self.library_root):
                    continue
                relative = changed.relative_to(self.library_root).as_posix()
                if changed.is_dir():
                    found = [p for p in changed.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
                else:
                    found = [changed] if changed.is_file() and changed.suffix.lower() in VIDEO_EXTENSIONS else []
                if not found:
                    result.stale_removed += self.repository.remove_path(self.location_id, relative)
                    continue
                for file_path in found:
                    title_dir = self._title_directory(file_path)
                    self._scan_file(file_path, title_dir, seen, result,
                                    is_loose_file=self._is_loose_file(file_path, title_dir))
            except Exception as error:
                result.errors += 1
        self.repository.commit()
        return result

    def _media_files(self, on_error: object | None = None):
        """Yield supported files while excluding review, hidden, and app folders."""
        for current, directories, files in os.walk(self.library_root, onerror=on_error):
            directories[:] = [name for name in directories
                              if not name.startswith(".") and name not in {"_Needs Manual Sorting", "_Duplicate Review"}]
            for name in files:
                path = Path(current) / name
                if path.suffix.lower() in VIDEO_EXTENSIONS:
                    yield path

    @staticmethod
    def _is_season(name: str) -> bool:
        return bool(re.match(r"^(?:season|cour|s)\s*0*\d+\b", name, re.I) or
                         re.search(r"(?:season|cour)\s*0*\d+\s*$", name, re.I))

    def _is_loose_file(self, file_path: Path, title_dir: Path) -> bool:
        if title_dir == self.library_root or self.library_type == "movies":
            return title_dir == self.library_root
        dirs = file_path.relative_to(self.library_root).parts[:-1]
        collection_names = {"binged", "watching", "watching - finished downloads",
                            "watching - unfinished downloads", "downloads", "downloads & unorganized",
                            "incomplete", "complete", "completed", "collection", "library"}
        return len(dirs) == 1 and dirs[0].casefold() in collection_names

    def _title_directory(self, file_path: Path) -> Path:
        """Resolve common flat-show and collection/show layouts conservatively."""
        dirs = file_path.relative_to(self.library_root).parts[:-1]
        if not dirs:
            return self.library_root
        if self.library_type == "movies":
            if dirs[0].casefold() == "movies" and len(dirs) > 1:
                return self.library_root / dirs[0] / dirs[1]
            return self.library_root / dirs[0]
        # Recommended layout: Series/Title/Season N/episode; Movies/Title (Year)/file.
        if dirs[0].casefold() in {"series", "anime", "tv shows", "cartoons"} and len(dirs) > 1:
            return self.library_root / dirs[0] / dirs[1]
        # A season immediately below the root title means this is a flat title library.
        if len(dirs) > 1 and self._is_season(dirs[1]):
            return self.library_root / dirs[0]
        # Legacy collection/show layout: collection/show/season/file.
        if len(dirs) > 2 and self._is_season(dirs[2]):
            return self.library_root / dirs[1]
        # When a direct root folder contains only season-like subfolders, it is a title.
        first = self.library_root / dirs[0]
        try:
            direct_children = [item.name for item in first.iterdir() if item.is_dir()] if first.is_dir() else []
        except OSError:
            direct_children = []
        if direct_children and all(self._is_season(name) for name in direct_children):
            return first
        # Common intake/collection names and collection parents with nested seasons.
        collection_names = {"binged", "watching", "watching - finished downloads",
                            "watching - unfinished downloads", "downloads", "downloads & unorganized",
                            "incomplete", "complete", "completed", "collection", "library"}
        if len(dirs) > 1 and (dirs[0].casefold() in collection_names or
                              (len(dirs) > 2 and self._is_season(dirs[2]))):
            return self.library_root / dirs[1]
        return first
    def _scan_file(self, file_path: Path, anime_dir: Path, seen_paths: set[str], result: ScanResult,
                   is_loose_file: bool = False) -> None:
        try:
            relative_path = file_path.relative_to(self.library_root).as_posix()
            seen_paths.add(relative_path)
            file_stat = file_path.stat()
            self.repository.relocate_by_identity(
                self.location_id, relative_path, int(file_stat.st_dev), int(file_stat.st_ino)
            )
            if self.library_type == "movies":
                title = anime_dir.name if anime_dir != self.library_root else file_path.stem
                parsed = ParsedMedia(title, None, None, None, True, False, None, False)
            elif is_loose_file:
                parsed = parse_loose_media_file(file_path, anime_dir)
            else:
                parsed = parse_media_file(file_path, anime_dir)
            existing = self.repository.existing_file(self.location_id, relative_path)
            unchanged = existing is not None and existing["file_size"] == file_stat.st_size and existing["modified_ns"] == file_stat.st_mtime_ns
            metadata, probe_error = None, None
            if unchanged and (existing["probe_status"] in {"ok", "failed"} or
                              (existing["probe_status"] == "disabled" and not self.probe_metadata)):
                result.reused_metadata += 1
                if existing["probe_status"] != "disabled":
                    metadata = MediaMetadata(existing["video_codec"], existing["audio_codec"], existing["width"], existing["height"], existing["duration_seconds"])
                probe_status, probe_error = existing["probe_status"], existing["probe_error"]
            elif not self.probe_metadata:
                probe_status, probe_error = "disabled", None
            else:
                try:
                    metadata, probe_status = probe_media(file_path), "ok"
                    result.probed += 1
                except Exception as error:  # One malformed file must not stop a scan.
                    probe_status, probe_error = "failed", str(error)
                    result.errors += 1
                    print(f"Warning: could not probe {file_path}: {error}")
            self.repository.save_file(self.location_id, relative_path, title=parsed.title, title_key=title_key(parsed.title), season_number=parsed.season_number, episode_number=parsed.episode_number, episode_end_number=parsed.episode_end_number, is_movie=parsed.is_movie, needs_review=parsed.needs_review, review_reason=parsed.review_reason, file_size=file_stat.st_size, modified_ns=file_stat.st_mtime_ns, device_id=int(file_stat.st_dev), inode=int(file_stat.st_ino), metadata=metadata, probe_status=probe_status, probe_error=probe_error, library_type=self.library_type)
            result.scanned += 1
        except Exception as error:  # Stat/parse/database failures are isolated per file too.
            result.errors += 1
            print(f"Warning: could not index {file_path}: {error}")
