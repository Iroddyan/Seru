"""Conservative parsing adapted directly from the existing anime_rename.py."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm"}
MOVIE_SIZE_THRESHOLD = 800 * 1024 * 1024
FORCE_MOVIE_FOLDERS = {("Jujutsu Kaisen", "Season 4 - Jujutsu Kaisen 0")}
SEASON_FOLDER_PATTERN = re.compile(r"^(season|cour|s)\s*\d+", re.IGNORECASE)

@dataclass(frozen=True)
class ParsedMedia:
    title: str
    season_number: int | None
    episode_number: int | None
    is_movie: bool
    needs_review: bool
    review_reason: str | None

def is_season_folder(name: str) -> bool:
    return bool(SEASON_FOLDER_PATTERN.match(name.strip()))

def extract_episode_number(filename: str) -> int | None:
    name = Path(filename).name
    patterns = [
        r"(?i)\bs\d+[\s._-]*e(\d{1,4})\b", r"(?i)\b(?:e|ep|episode)[\s._-]*(\d{1,4})\b",
        r"(?i)\[\s*(?:s\d+[\s._-]*)?e\s*(\d{1,4})\s*\]", r"(?i)\b(?:ova|special|sp)[\s._-]*(\d{1,4})\b",
        r"(?i)(?:^|[\s._\-\[\(/])(\d{1,4})(?:[\s._\-\]\)/]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            return int(match.group(1))
    return None

def parse_media_file(file_path: Path, anime_dir: Path) -> ParsedMedia:
    """Use the renamer's forced-movie, folder, size, season, and episode rules."""
    relative_path = file_path.relative_to(anime_dir)
    parent_folders = relative_path.parts[:-1]
    title = anime_dir.name.strip() or "Unknown / Needs Review"
    forced_movie = any((title, folder) in FORCE_MOVIE_FOLDERS for folder in parent_folders)
    in_season_folder = any(is_season_folder(folder) for folder in parent_folders)
    if forced_movie or (not in_season_folder and file_path.stat().st_size > MOVIE_SIZE_THRESHOLD):
        return ParsedMedia(title, None, None, True, False, None)
    season_number = None
    for folder in parent_folders:
        match = re.search(r"\d+", folder)
        if is_season_folder(folder) and match:
            season_number = int(match.group())
            break
    episode_number = extract_episode_number(file_path.name)
    if episode_number is None:
        return ParsedMedia(title, season_number, None, False, True, "Could not confidently parse an episode number")
    return ParsedMedia(title, season_number, episode_number, False, False, None)
