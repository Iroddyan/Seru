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
        episode_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(episodes)")}
        if "episode_end_number" not in episode_columns:
            self.connection.execute("ALTER TABLE episodes ADD COLUMN episode_end_number INTEGER")
        anime_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(anime)")}
        if "favorite" not in anime_columns:
            self.connection.execute("ALTER TABLE anime ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        media_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(media_files)")}
        if "discovered_at" not in media_columns:
            self.connection.execute("ALTER TABLE media_files ADD COLUMN discovered_at TEXT")
            self.connection.execute("UPDATE media_files SET discovered_at = datetime(modified_ns / 1000000000, 'unixepoch') WHERE discovered_at IS NULL")
        self.connection.commit()
    def close(self) -> None: self.connection.close()
    def begin_scan(self, location_id: str, root_path: Path) -> None:
        self.connection.execute("INSERT INTO library_locations(location_id, root_path) VALUES(?, ?) ON CONFLICT(location_id) DO UPDATE SET root_path=excluded.root_path, updated_at=CURRENT_TIMESTAMP", (location_id, str(root_path.resolve())))
    def existing_file(self, location_id: str, relative_path: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM media_files WHERE location_id = ? AND relative_path = ?", (location_id, relative_path)).fetchone()
    def save_file(self, location_id: str, relative_path: str, *, title: str, title_key: str, season_number: int | None, episode_number: int | None, episode_end_number: int | None, is_movie: bool, needs_review: bool, review_reason: str | None, file_size: int, modified_ns: int, metadata: object | None, probe_status: str, probe_error: str | None) -> None:
        anime_id = self.connection.execute("INSERT INTO anime(title, title_key, needs_review) VALUES (?, ?, ?) ON CONFLICT(title_key) DO UPDATE SET needs_review=MAX(anime.needs_review, excluded.needs_review) RETURNING anime_id", (title, title_key, int(needs_review))).fetchone()[0]
        previous = self.existing_file(location_id, relative_path)
        if previous is None:
            episode_id = self.connection.execute("INSERT INTO episodes(anime_id, season_number, episode_number, episode_end_number, is_movie, needs_review, review_reason) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING episode_id", (anime_id, season_number, episode_number, episode_end_number, int(is_movie), int(needs_review), review_reason)).fetchone()[0]
        else:
            episode_id = previous["episode_id"]
            self.connection.execute("UPDATE episodes SET anime_id = ?, season_number = ?, episode_number = ?, episode_end_number = ?, is_movie = ?, needs_review = ?, review_reason = ? WHERE episode_id = ?", (anime_id, season_number, episode_number, episode_end_number, int(is_movie), int(needs_review), review_reason, episode_id))
        values = (None, None, None, None, None) if metadata is None else (metadata.video_codec, metadata.audio_codec, metadata.width, metadata.height, metadata.duration_seconds)
        discovered_at = previous["discovered_at"] if previous is not None else None
        if previous is None:
            self.connection.execute("INSERT INTO media_files(location_id, relative_path, episode_id, file_size, modified_ns, video_codec, audio_codec, width, height, duration_seconds, probe_status, probe_error, discovered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))", (location_id, relative_path, episode_id, file_size, modified_ns, *values, probe_status, probe_error, discovered_at))
        else:
            self.connection.execute("UPDATE media_files SET episode_id = ?, file_size = ?, modified_ns = ?, video_codec = ?, audio_codec = ?, width = ?, height = ?, duration_seconds = ?, probe_status = ?, probe_error = ?, discovered_at = COALESCE(?, discovered_at, CURRENT_TIMESTAMP) WHERE media_file_id = ?", (episode_id, file_size, modified_ns, *values, probe_status, probe_error, discovered_at, previous["media_file_id"]))
    def remove_stale_files(self, location_id: str, seen_paths: set[str]) -> int:
        rows = self.connection.execute("SELECT media_file_id, relative_path FROM media_files WHERE location_id = ?", (location_id,)).fetchall()
        stale_ids = [row["media_file_id"] for row in rows if row["relative_path"] not in seen_paths]
        self.connection.executemany("DELETE FROM media_files WHERE media_file_id = ?", ((item,) for item in stale_ids))
        self.connection.execute("DELETE FROM episodes WHERE episode_id NOT IN (SELECT episode_id FROM media_files)")
        self.connection.execute("DELETE FROM anime WHERE anime_id NOT IN (SELECT anime_id FROM episodes)")
        return len(stale_ids)
    def commit(self) -> None: self.connection.commit()
    def record_launch(self, anime_id: int, episode_id: int) -> None:
        """Persist a user-initiated playback attempt owned by Seru.

        This deliberately does not read Celluloid or mpv resume state.  It is
        the small, reliable history used by the later Home view.
        """
        self.connection.execute(
            "INSERT INTO launches(anime_id, episode_id) VALUES (?, ?)",
            (anime_id, episode_id),
        )
        self.connection.commit()
    def set_favorite(self, anime_id: int, favorite: bool) -> None:
        self.connection.execute("UPDATE anime SET favorite = ? WHERE anime_id = ?", (int(favorite), anime_id))
        self.connection.commit()
    def counts(self, location_id: str) -> dict[str, int]:
        row = self.connection.execute("SELECT COUNT(*) files, COUNT(DISTINCT e.anime_id) titles, COALESCE(SUM(CASE WHEN e.is_movie = 0 AND e.needs_review = 0 THEN 1 ELSE 0 END), 0) episodes, COALESCE(SUM(CASE WHEN e.is_movie = 1 THEN 1 ELSE 0 END), 0) movies, COALESCE(SUM(CASE WHEN e.needs_review = 1 THEN 1 ELSE 0 END), 0) needs_review FROM media_files m JOIN episodes e ON e.episode_id=m.episode_id WHERE m.location_id = ?", (location_id,)).fetchone()
        return dict(row)

    @staticmethod
    def _collection_filter(folder_filter: str | None) -> tuple[str, tuple[str, ...]]:
        """Filter by detected category in the first component of a relative path.

        A collection containing ``watch`` belongs to Watching even if it also
        contains ``download`` in its name.  This lets names such as
        "Watching - Finished Downloads" remain distinct from a general
        downloads intake collection without encoding either full folder name.
        """
        if folder_filter is None:
            return "", ()
        collection = "LOWER(SUBSTR(m.relative_path, 1, INSTR(m.relative_path || '/', '/') - 1))"
        if folder_filter == "downloads":
            return f" AND {collection} LIKE ? AND {collection} NOT LIKE ?", ("%download%", "%watch%")
        return f" AND {collection} LIKE ?", (f"%{folder_filter.casefold()}%",)

    def library_statistics(self, location_id: str) -> tuple[sqlite3.Row, list[sqlite3.Row], list[sqlite3.Row]]:
        """Aggregate the local index for the Statistics page only.

        No filesystem walk or media probing happens here.  Screen time uses
        the same pragmatic estimates as anime_smart_list.sh: 24 minutes per
        episode and 110 minutes per movie.
        """
        summary = self.connection.execute(
            """SELECT COUNT(DISTINCT e.anime_id) AS titles,
                      COALESCE(SUM(CASE WHEN e.is_movie = 0 AND e.needs_review = 0 THEN 1 ELSE 0 END), 0) AS episodes,
                      COALESCE(SUM(CASE WHEN e.is_movie = 1 THEN 1 ELSE 0 END), 0) AS movies,
                      COALESCE(SUM(m.file_size), 0) AS total_size
               FROM media_files AS m
               JOIN episodes AS e ON e.episode_id = m.episode_id
               WHERE m.location_id = ?""",
            (location_id,),
        ).fetchone()
        codecs = self.connection.execute(
            """SELECT COALESCE(m.video_codec, 'unknown') AS label, COUNT(*) AS file_count,
                      COALESCE(SUM(m.file_size), 0) AS total_size
               FROM media_files AS m
               WHERE m.location_id = ?
               GROUP BY COALESCE(m.video_codec, 'unknown')
               ORDER BY file_count DESC, label COLLATE NOCASE""",
            (location_id,),
        ).fetchall()
        resolutions = self.connection.execute(
            """SELECT CASE WHEN m.height IS NULL THEN 'unknown' ELSE CAST(m.height AS TEXT) || 'p' END AS label,
                      COUNT(*) AS file_count, COALESCE(SUM(m.file_size), 0) AS total_size
               FROM media_files AS m
               WHERE m.location_id = ?
               GROUP BY CASE WHEN m.height IS NULL THEN 'unknown' ELSE CAST(m.height AS TEXT) || 'p' END
               ORDER BY CASE WHEN m.height IS NULL THEN 0 ELSE m.height END DESC, label""",
            (location_id,),
        ).fetchall()
        return summary, codecs, resolutions

    def list_anime(self, location_id: str, search: str = "", folder_filter: str | None = None,
                   favorites_only: bool = False) -> list[sqlite3.Row]:
        """Return library rows from the cache; never inspect the filesystem."""
        term = f"%{search.strip()}%"
        filter_sql, filter_args = self._collection_filter(folder_filter)
        if favorites_only:
            filter_sql += " AND a.favorite = 1"
        return self.connection.execute(
            """SELECT a.anime_id, a.title, a.favorite,
                      COUNT(m.media_file_id) AS file_count,
                      SUM(CASE WHEN e.is_movie = 0 AND e.needs_review = 0 THEN 1 ELSE 0 END) AS episode_count,
                      SUM(CASE WHEN e.is_movie = 1 THEN 1 ELSE 0 END) AS movie_count,
                      SUM(m.file_size) AS total_size
               FROM anime a
               JOIN episodes e ON e.anime_id = a.anime_id
               JOIN media_files m ON m.episode_id = e.episode_id
               WHERE m.location_id = ? AND a.title LIKE ?""" + filter_sql + """
               GROUP BY a.anime_id
               ORDER BY a.title COLLATE NOCASE""",
            (location_id, term, *filter_args),
        ).fetchall()

    def anime_detail(self, anime_id: int, location_id: str, folder_filter: str | None = None) -> sqlite3.Row | None:
        filter_sql, filter_args = self._collection_filter(folder_filter)
        return self.connection.execute(
            """SELECT a.anime_id, a.title, a.favorite, COUNT(m.media_file_id) AS file_count,
                      SUM(CASE WHEN e.is_movie = 0 AND e.needs_review = 0 THEN 1 ELSE 0 END) AS episode_count,
                      SUM(CASE WHEN e.is_movie = 1 THEN 1 ELSE 0 END) AS movie_count,
                      SUM(m.file_size) AS total_size
               FROM anime a JOIN episodes e ON e.anime_id = a.anime_id
               JOIN media_files m ON m.episode_id = e.episode_id
               WHERE a.anime_id = ? AND m.location_id = ?""" + filter_sql + """
               GROUP BY a.anime_id""",
            (anime_id, location_id, *filter_args),
        ).fetchone()

    def home_dashboard(self, location_id: str) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
        """Return the launch and discovery data used by Home, without scanning."""
        continue_watching = self.connection.execute(
            """SELECT a.title, e.season_number, e.episode_number, e.episode_end_number,
                      e.is_movie, m.relative_path, l.timestamp
               FROM launches AS l
               JOIN anime AS a ON a.anime_id = l.anime_id
               JOIN episodes AS e ON e.episode_id = l.episode_id
               JOIN media_files AS m ON m.episode_id = e.episode_id
               WHERE m.location_id = ?
                 AND l.launch_id = (
                     SELECT newer.launch_id FROM launches AS newer
                     WHERE newer.anime_id = l.anime_id
                     ORDER BY newer.timestamp DESC, newer.launch_id DESC LIMIT 1
                 )
               ORDER BY l.timestamp DESC, l.launch_id DESC LIMIT 10""",
            (location_id,),
        ).fetchall()
        recently_added = self.connection.execute(
            """SELECT a.title, e.season_number, e.episode_number, e.episode_end_number,
                      e.is_movie, m.relative_path, m.discovered_at
               FROM media_files AS m
               JOIN episodes AS e ON e.episode_id = m.episode_id
               JOIN anime AS a ON a.anime_id = e.anime_id
               WHERE m.location_id = ?
               ORDER BY m.discovered_at DESC, m.media_file_id DESC LIMIT 10""",
            (location_id,),
        ).fetchall()
        return continue_watching, recently_added

    def anime_episodes(self, anime_id: int, location_id: str, folder_filter: str | None = None) -> list[sqlite3.Row]:
        filter_sql, filter_args = self._collection_filter(folder_filter)
        return self.connection.execute(
            """SELECT e.episode_id, e.season_number, e.episode_number, e.episode_end_number, e.is_movie, e.needs_review,
                      e.review_reason, m.relative_path, m.duration_seconds, m.height
               FROM episodes e JOIN media_files m ON m.episode_id = e.episode_id
               WHERE e.anime_id = ? AND m.location_id = ?""" + filter_sql + """
               ORDER BY e.is_movie, e.season_number IS NULL, e.season_number,
                        e.episode_number IS NULL, e.episode_number, m.relative_path""",
            (anime_id, location_id, *filter_args),
        ).fetchall()
