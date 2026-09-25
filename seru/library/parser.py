"""Filename and directory parsing adapted from the current anime_rename.py."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".m4v", ".mov"}
MOVIE_SIZE_THRESHOLD = 800 * 1024 * 1024
ABSOLUTE_NUMBERING_SHOWS = {"Bleach", "Bleach; Thousand-Year Blood War"}
FORCE_MOVIE_FOLDERS = {("Jujutsu Kaisen", "Season 4 - Jujutsu Kaisen 0")}
MANUAL_REVIEW_FOLDER = "_Needs Manual Sorting"
SEASON_FOLDER_PATTERN = re.compile(r"^(?:season|cour|s)\s*0*(\d+)\b", re.I)
SEASON_IN_FILENAME_PATTERN = re.compile(r"\b(?:season|s)\s*0*(\d{1,2})(?=\b|e)", re.I)

@dataclass(frozen=True)
class ParsedMedia:
    title: str
    season_number: int | None
    episode_number: int | None
    is_movie: bool
    needs_review: bool
    review_reason: str | None
    absolute_numbering: bool

def season_number(folder: str) -> int | None:
    match = SEASON_FOLDER_PATTERN.match(folder.strip())
    return int(match.group(1)) if match else None

def is_season_folder(name: str) -> bool:
    return season_number(name) is not None

def season_number_in_filename(filename: str) -> int | None:
    match = SEASON_IN_FILENAME_PATTERN.search(Path(filename).stem)
    return int(match.group(1)) if match else None

def extract_episode_number(filename: str) -> int | None:
    """Use the renamer's explicit-first parser, avoiding resolution/year tokens."""
    stem = Path(filename).stem
    for pattern in (
        r"\bs\d{1,2}\s*[._ -]*e\s*(\d{1,4})\b", r"\b(?:e|ep|episode)\s*[._ -]*(\d{1,4})\b",
        r"\[\s*(?:s\d+\s*)?e\s*(\d{1,4})\s*\]", r"\b(?:ova|special|sp)\s*[._ -]*(\d{1,4})\b",
    ):
        match = re.search(pattern, stem, re.I)
        if match: return int(match.group(1))
    for match in re.finditer(r"(?<!\d)(\d{1,4})(?!\d)", stem):
        number = int(match.group(1))
        if number not in {480, 576, 720, 1080, 1440, 2160, 4320} and not 1900 <= number <= 2100:
            return number
    return None

def looks_like_show_dir(directory: Path) -> bool:
    if season_number(directory.name) is not None: return False
    return any(path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS for path in directory.rglob("*"))

def discover_show_dirs(root: Path) -> list[Path]:
    """Mirror the renamer's one-or-two-level collection/show discovery."""
    top_level = [path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")]
    shows: list[Path] = []
    for directory in top_level:
        if directory.name == MANUAL_REVIEW_FOLDER: continue
        children = [path for path in directory.iterdir() if path.is_dir() and path.name != MANUAL_REVIEW_FOLDER]
        child_shows = [path for path in children if looks_like_show_dir(path)]
        if child_shows: shows.extend(child_shows)
        elif looks_like_show_dir(directory): shows.append(directory)
    return sorted(set(shows))

def parse_media_file(file_path: Path, anime_dir: Path) -> ParsedMedia:
    """Classify a file with current forced-movie and season precedence rules."""
    parent_folders = file_path.relative_to(anime_dir).parts[:-1]
    title = anime_dir.name.strip() or "Unknown / Needs Review"
    absolute_numbering = title in ABSOLUTE_NUMBERING_SHOWS
    forced_movie = any((title, folder) in FORCE_MOVIE_FOLDERS for folder in parent_folders)
    seasons = [number for folder in parent_folders if (number := season_number(folder)) is not None]
    if forced_movie or (not seasons and file_path.stat().st_size > MOVIE_SIZE_THRESHOLD):
        return ParsedMedia(title, None, None, True, False, None, absolute_numbering)
    episode_number = extract_episode_number(file_path.name)
    if episode_number is None:
        return ParsedMedia(title, None, None, False, True, "Could not confidently parse an episode number", absolute_numbering)
    effective_season = season_number_in_filename(file_path.name) or (seasons[0] if seasons else None)
    # Absolute-numbered shows accept optional S## source tokens but persist
    # their canonical identity as E### only, avoiding season-token conflicts.
    if absolute_numbering: effective_season = None
    return ParsedMedia(title, effective_season, episode_number, False, False, None, absolute_numbering)
