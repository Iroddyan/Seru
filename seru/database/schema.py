"""Schema for Seru's rebuildable local SQLite index."""
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS library_locations (
 location_id TEXT PRIMARY KEY, root_path TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS anime (
 anime_id INTEGER PRIMARY KEY, title TEXT NOT NULL, title_key TEXT NOT NULL UNIQUE, needs_review INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS episodes (
 episode_id INTEGER PRIMARY KEY, anime_id INTEGER NOT NULL REFERENCES anime(anime_id) ON DELETE CASCADE,
 season_number INTEGER, episode_number INTEGER, is_movie INTEGER NOT NULL DEFAULT 0,
 needs_review INTEGER NOT NULL DEFAULT 0, review_reason TEXT
);
CREATE TABLE IF NOT EXISTS media_files (
 media_file_id INTEGER PRIMARY KEY, location_id TEXT NOT NULL REFERENCES library_locations(location_id) ON DELETE CASCADE,
 relative_path TEXT NOT NULL, episode_id INTEGER NOT NULL REFERENCES episodes(episode_id) ON DELETE CASCADE,
 file_size INTEGER NOT NULL, modified_ns INTEGER NOT NULL, video_codec TEXT, audio_codec TEXT, width INTEGER, height INTEGER,
 duration_seconds REAL, probe_status TEXT NOT NULL DEFAULT 'pending', probe_error TEXT,
 UNIQUE(location_id, relative_path)
);
CREATE INDEX IF NOT EXISTS media_files_location_path_idx ON media_files(location_id, relative_path);
CREATE INDEX IF NOT EXISTS episodes_anime_idx ON episodes(anime_id);
"""
