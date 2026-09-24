"""SQLite access for Seru's rebuildable local index."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .schema import SCHEMA_SQL

class LibraryRepository:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA_SQL)
    def close(self) -> None: self.connection.close()
    def begin_scan(self, location_id: str, root_path: Path) -> None:
        self.connection.execute("INSERT INTO library_locations(location_id, root_path) VALUES(?, ?) ON CONFLICT(location_id) DO UPDATE SET root_path=excluded.root_path, updated_at=CURRENT_TIMESTAMP", (location_id, str(root_path.resolve())))
    def existing_file(self, location_id: str, relative_path: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM media_files WHERE location_id = ? AND relative_path = ?", (location_id, relative_path)).fetchone()
    def save_file(self, location_id: str, relative_path: str, *, title: str, title_key: str, season_number: int | None, episode_number: int | None, is_movie: bool, needs_review: bool, review_reason: str | None, file_size: int, modified_ns: int, metadata: object | None, probe_status: str, probe_error: str | None) -> None:
        anime_id = self.connection.execute("INSERT INTO anime(title, title_key, needs_review) VALUES (?, ?, ?) ON CONFLICT(title_key) DO UPDATE SET needs_review=MAX(anime.needs_review, excluded.needs_review) RETURNING anime_id", (title, title_key, int(needs_review))).fetchone()[0]
        episode_id = self.connection.execute("INSERT INTO episodes(anime_id, season_number, episode_number, is_movie, needs_review, review_reason) VALUES (?, ?, ?, ?, ?, ?) RETURNING episode_id", (anime_id, season_number, episode_number, int(is_movie), int(needs_review), review_reason)).fetchone()[0]
        values = (None, None, None, None, None) if metadata is None else (metadata.video_codec, metadata.audio_codec, metadata.width, metadata.height, metadata.duration_seconds)
        previous = self.existing_file(location_id, relative_path)
        if previous is not None: self.connection.execute("DELETE FROM media_files WHERE media_file_id = ?", (previous["media_file_id"],))
        self.connection.execute("INSERT INTO media_files(location_id, relative_path, episode_id, file_size, modified_ns, video_codec, audio_codec, width, height, duration_seconds, probe_status, probe_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (location_id, relative_path, episode_id, file_size, modified_ns, *values, probe_status, probe_error))
    def remove_stale_files(self, location_id: str, seen_paths: set[str]) -> int:
        rows = self.connection.execute("SELECT media_file_id, relative_path FROM media_files WHERE location_id = ?", (location_id,)).fetchall()
        stale_ids = [row["media_file_id"] for row in rows if row["relative_path"] not in seen_paths]
        self.connection.executemany("DELETE FROM media_files WHERE media_file_id = ?", ((item,) for item in stale_ids))
        self.connection.execute("DELETE FROM episodes WHERE episode_id NOT IN (SELECT episode_id FROM media_files)")
        self.connection.execute("DELETE FROM anime WHERE anime_id NOT IN (SELECT anime_id FROM episodes)")
        return len(stale_ids)
    def commit(self) -> None: self.connection.commit()
    def counts(self, location_id: str) -> dict[str, int]:
        row = self.connection.execute("SELECT COUNT(*) files, COUNT(DISTINCT e.anime_id) titles, COALESCE(SUM(CASE WHEN e.is_movie = 0 AND e.needs_review = 0 THEN 1 ELSE 0 END), 0) episodes, COALESCE(SUM(CASE WHEN e.is_movie = 1 THEN 1 ELSE 0 END), 0) movies, COALESCE(SUM(CASE WHEN e.needs_review = 1 THEN 1 ELSE 0 END), 0) needs_review FROM media_files m JOIN episodes e ON e.episode_id=m.episode_id WHERE m.location_id = ?", (location_id,)).fetchone()
        return dict(row)
