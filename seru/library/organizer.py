"""Reviewable, collision-safe file organization plans."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import uuid

from ..database.repository import LibraryRepository
from .parser import ABSOLUTE_NUMBERING_SHOWS, VIDEO_EXTENSIONS, parse_media_file
from .scanner import LibraryScanner


@dataclass(frozen=True)
class FileAction:
    source: Path
    destination: Path


@dataclass
class OrganizationPlan:
    actions: list[FileAction]
    skipped: list[str]


def _safe_segment(value: str) -> str:
    return value.replace("/", "-").replace("\\", "-").strip().strip(".") or "Unknown"


def build_plan(repository: LibraryRepository, root: Path, library_type: str, location_id: str) -> OrganizationPlan:
    root = root.resolve()
    scanner = LibraryScanner(repository, root, location_id, library_type)
    actions: list[FileAction] = []
    skipped: list[str] = []
    destinations: set[Path] = set()
    for source in scanner._media_files():
        try:
            title_dir = scanner._title_directory(source)
            if library_type == "movies":
                if title_dir == root:
                    skipped.append(f"{source}: movie title is uncertain")
                    continue
                title = _safe_segment(title_dir.name)
                movie_root = root / "Movies" if (root / "Movies").is_dir() else root
                destination_dir = movie_root / title
                filename = f"{title}{source.suffix.lower()}"
            else:
                if title_dir == root:
                    skipped.append(f"{source}: series title is uncertain")
                    continue
                parsed = parse_media_file(source, title_dir)
                if parsed.needs_review:
                    skipped.append(f"{source}: {parsed.review_reason or 'needs review'}")
                    continue
                title = _safe_segment(parsed.title)
                series_root = root / "Series" if (root / "Series").is_dir() else root
                destination_dir = series_root / title
                if parsed.is_movie:
                    filename = f"{title}{source.suffix.lower()}"
                else:
                    season = parsed.season_number or 1
                    destination_dir /= f"Season {season:02d}"
                    location = repository.existing_file(location_id, source.relative_to(root).as_posix())
                    if location is None or not location["probe_status"] == "ok":
                        skipped.append(f"{source}: technical metadata is unavailable")
                        continue
                    resolution = f"{location['height']}p" if location["height"] else "UNK"
                    video = (location["video_codec"] or "UNK").upper()
                    audio = (location["audio_codec"] or "UNK").upper()
                    number = f"{parsed.episode_number:03d}"
                    if parsed.episode_end_number is not None:
                        number += f"-E{parsed.episode_end_number:03d}"
                    if parsed.title in ABSOLUTE_NUMBERING_SHOWS:
                        tag = f"E{number}"
                    else:
                        tag = f"S{season:02d}E{number}"
                    filename = f"{title} - {tag} - [{resolution} {video} {audio}]{source.suffix.lower()}"
            destination = destination_dir / filename
            if destination == source:
                continue
            if destination.exists() or destination in destinations:
                skipped.append(f"{source}: destination already exists: {destination}")
                continue
            destinations.add(destination)
            actions.append(FileAction(source, destination))
        except (OSError, ValueError, TypeError) as error:
            skipped.append(f"{source}: {error}")
    return OrganizationPlan(actions, skipped)


def apply_plan(plan: OrganizationPlan, root: Path) -> tuple[Path, list[str]]:
    """Apply confirmed changes and save a manifest, reporting partial failures."""
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "seru" / "operations"
    base.mkdir(parents=True, exist_ok=True)
    manifest = base / f"organization-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.jsonl"
    errors: list[str] = []
    with manifest.open("x", encoding="utf-8") as journal:
        journal.write(json.dumps({"root": str(root.resolve()), "type": "organization"}) + "\n")
        journal.flush()
        os.fsync(journal.fileno())
    for action in plan.actions:
        row = {"old_path": str(action.source), "new_path": str(action.destination)}
        try:
            if not action.source.exists() or action.destination.exists():
                raise FileExistsError("source disappeared or destination now exists")
            action.destination.parent.mkdir(parents=True, exist_ok=True)
            with manifest.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps({**row, "status": "in_progress"}) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
            action.source.rename(action.destination)
            with manifest.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps({**row, "status": "complete"}) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
        except OSError as error:
            errors.append(f"{action.source}: {error}")
            try:
                with manifest.open("a", encoding="utf-8") as journal:
                    journal.write(json.dumps({**row, "status": "failed", "error": str(error)}) + "\n")
                    journal.flush()
                    os.fsync(journal.fileno())
            except OSError:
                pass
    return manifest, errors


def undo_manifest(manifest: Path) -> list[str]:
    lines = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) == 1 and "moves" in lines[0]:
        moves = lines[0].get("moves", [])
    else:
        latest: dict[tuple[str, str], dict[str, str]] = {}
        for row in lines[1:]:
            latest[(row["old_path"], row["new_path"])] = row
        moves = [row for row in latest.values()
                 if row.get("status") == "complete" or
                 (row.get("status") == "in_progress" and Path(row["new_path"]).exists()
                  and not Path(row["old_path"]).exists())]
    blocked = [row for row in moves if not Path(row["new_path"]).exists() or Path(row["old_path"]).exists()]
    if blocked:
        return [f"Cannot undo because a destination is missing or original path is occupied: {row['new_path']}" for row in blocked]
    errors = []
    for row in reversed(moves):
        source, destination = Path(row["new_path"]), Path(row["old_path"])
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
        except OSError as error:
            errors.append(f"{source}: {error}")
    return errors
