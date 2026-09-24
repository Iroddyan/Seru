"""CLI entry point: ``python -m seru.library.scan [library_root]``."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from ..database.repository import LibraryRepository
from .scanner import LibraryScanner

DEFAULT_LIBRARY_ROOT = "/run/media/iroddyan/Warehouse/Theatre/Anime"
def default_database_path() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "seru" / "library.sqlite3"
def main() -> int:
    parser = argparse.ArgumentParser(description="Build or update Seru's local library index.")
    parser.add_argument("library_root", nargs="?", default=os.environ.get("SERU_LIBRARY_ROOT", DEFAULT_LIBRARY_ROOT))
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument("--location-id", default="default", help="Stable identifier for this configured library location.")
    args = parser.parse_args()
    repository = LibraryRepository(args.database)
    try:
        result = LibraryScanner(repository, Path(args.library_root), args.location_id).scan()
        counts = repository.counts(args.location_id)
    finally:
        repository.close()
    print("Scan complete: {scanned} files scanned; {probed} probed; {reused_metadata} metadata records reused; {stale_removed} stale files removed; {errors} errors.".format(**result.__dict__))
    print("Library: {titles} titles; {episodes} episodes; {movies} movies; {needs_review} need review.".format(**counts))
    return 0
if __name__ == "__main__": raise SystemExit(main())
