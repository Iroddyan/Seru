# セル / Seru — Revised Build Plan (Python Edition)
---

## Bit 0 — Standing Context

**What this is:** セル (Seru) — a native GNOME library manager for a local anime collection. It browses, catalogs, and launches playback. It is **not** a media player and does not do transcoding/streaming itself.

**Stack:**
- Python 3
- GTK4 + libadwaita via **PyGObject**
- SQLite via the standard library `sqlite3` module
- `ffprobe` for media metadata, invoked via `subprocess`
- Celluloid as the external player (launched via `subprocess`, never a shell)

**Target machine:**
```
Dell OptiPlex 9020
Intel Core i5-4590
RAM: 8 GB
GPU: Intel HD Graphics 4600
OS: Fedora Linux 44 (GNOME 50, Wayland)
```
Modest but not starved. Keep memory and GPU load light (lazy-load posters/lists, avoid heavy animation, efficient queries) but don't over-engineer against a 4 GB assumption — you have real headroom.

**Paths:**
```
Project dir (repo root): /run/media/iroddyan/Warehouse/Projects/Seru
Library dir: /run/media/iroddyan/Warehouse/Theatre/Anime   (must stay configurable — the drive won't always mount at exactly this path)
```
The Python package itself, imported as `seru` (lowercase, standard Python convention), lives inside that repo root — the two different cases are intentional, not a typo.

**Existing tools — inspect and reuse, do not blindly reimplement:**
- `anime_smart_list.sh` — already computes title/season/episode/movie detection, codec & resolution stats, screen-time estimates, watch/completion grouping, diagnostics. Treat its logic as the reference implementation for Statistics/Diagnostics later. Its own episode/movie counting is a simple filename-regex heuristic (no tag found → counted as a movie) — useful as a second opinion, not an oracle to force-match exactly.
- `anime_rename.py` — has a working filename parser tested against the real library, since rewritten to add real per-show exceptions. **Adapt its parsing logic directly into Seru's parser rather than writing a new one from a prose description**, and make sure these specific pieces come across, not just the general shape:
  - `ABSOLUTE_NUMBERING_SHOWS` (currently Bleach and Bleach; Thousand-Year Blood War) — these use a canonical filename with **no season token** (`Bleach - E221 - [...]`, not `S01E221`). The canonical-episode pattern must treat the season prefix as optional, or these files get misread or rejected.
  - `FORCE_MOVIE_FOLDERS` — explicit per-(show, folder) overrides for movie detection that the general season-absent/800MB heuristic can't catch alone (currently one entry, for Jujutsu Kaisen).
  - `MANUAL_REVIEW_FOLDER` (`_Needs Manual Sorting`) — both scripts explicitly skip this folder name when walking the tree; Seru's scanner should too, or it'll try to treat it as a show.
  - `SKIP_SHOWS` (currently Demon Slayer) is a renamer-only concept (leave its filenames alone) — it does **not** mean Seru's scanner should skip indexing that show.
  - This list of exceptions will keep changing as the library grows — re-read the actual current script before trusting a port of it more than a session or two old. Leave both scripts themselves untouched.

**Non-negotiable rules:**
1. The filesystem is the source of truth. SQLite is a rebuildable cache/index — if deleted, Seru rebuilds it from disk. Never assume the DB.
2. Seru never renames, moves, deletes, or reorganizes anything in the library automatically.
3. No shell strings, ever. All subprocess calls (`ffprobe`, `celluloid`) use an argument list (`subprocess.run([...])` / `subprocess.Popen([...])`), never `shell=True` or string concatenation. Treat every filename/path as untrusted input.
4. Scanning and ffprobe calls must run off the GTK main thread (Python `threading`), with results marshaled back to the UI via `GLib.idle_add`. The window must never freeze during a scan.
5. Every per-file parse or ffprobe call is wrapped in its own `try/except`. One malformed file must never abort a whole scan. Anything that can't be confidently parsed is marked `Unknown / Needs Review`, never silently dropped and never silently guessed.
6. Only probe files that are new, changed, or missing metadata — never re-probe the whole library on every launch.
7. Must work fully offline. No online metadata/artwork provider is a dependency of core scanning, ever (may be added later as a strictly optional feature).
8. App ID: `com.iroddyan.Seru`.

**Module layout (adapt as needed, don't over-engineer up front):**
```
seru/
├── __main__.py
├── app.py
├── ui/
│   ├── window.py
│   ├── navigation.py
│   ├── library.py
│   ├── anime_detail.py
│   └── episode_list.py        # statistics.py (Bit 7), watching.py/downloads.py
│                               # (Bit 8, folder-filtered views), dashboard.py
│                               # (Bit 10, last) and preferences.py come later
├── library/
│   ├── scanner.py
│   ├── parser.py              # adapted from anime_rename.py
│   └── service.py             # watcher.py comes later
├── media/
│   ├── ffprobe.py
│   └── player.py
├── database/
│   ├── schema.py
│   └── repository.py
├── models/
│   ├── anime.py
│   ├── episode.py
│   └── media.py
└── config/
    └── __init__.py
```

**GNOME design principles:** libadwaita components, header bars, sidebar navigation, standard symbolic icons, adaptive layouts, system theme integration. Avoid custom title bars, gradients, glassmorphism, neon "gamer" aesthetics, anime wallpaper. Subtle and mature — a serious desktop app that happens to be about anime.

**Explicitly deferred — do not build any of this yet:** embedded mpv, online anime APIs, automatic metadata/artwork downloading, automatic renaming or file organization, torrents, streaming, accounts, cloud sync, social features, recommendations, subtitle downloading, mobile apps, filesystem watcher/auto-rescan, and Diagnostics. Those come later, if at all.

Statistics, Watching, Downloads, Favorites, and Home are **not** on the "don't build" list — they're specified below as Bits 7–10, to be built only after the Bit 6 checkpoint. Two design notes that apply to all of them, decided up front so Codex doesn't reinvent them differently each time:
- Watching and Downloads are **folder-driven, not progress-tracking**. The existing library already sorts titles into categories on disk (e.g. `Watching - Finished/Unfinished Downloads`, `Downloads & Unorganized`). Detect these folder categories the same way Library detection already works (Section 3's rule: detect, don't hardcode) and treat "Watching"/"Downloads" as filtered views over that, not as a per-episode resume-position system.
- Do **not** read Celluloid/mpv's `watch_later` resume files to infer progress. That mechanism is internal to mpv, undocumented for external use, and known to behave inconsistently even for mpv's own resume-on-open feature. Instead, "Continue Watching" is powered by a `launches` table that Seru itself writes every time the user presses ▶ (added in Bit 5, surfaced in Bit 10) — reliable, and entirely under Seru's own control.

---

## Bit 1 — Environment Smoke Test (throwaway script, not part of the app)

Before any architecture: prove the toolchain actually works together on this machine.

Write a single standalone script, `scan_test.py`, that:
- Walks the configured library root (non-recursively is fine for this test)
- Finds a handful of real video files
- Runs `ffprobe -v quiet -print_format json -show_format -show_streams <file>` on **one** real file via `subprocess.run([...], capture_output=True)`
- Parses the JSON and prints codec, resolution, and duration as a plain dict

No GTK, no SQLite, no PyGObject import yet. This only exists to confirm Python + subprocess + ffprobe + your real filesystem cooperate before anything else gets built on top.

**Acceptance:** it prints real codec/resolution/duration for at least one real episode file, no crash.

---

## Bit 2 — Phase 1: Project Foundation

Deliverable:
- `seru/` package skeleton per the layout above
- Dependency file (PyGObject only for now — don't add anything heavier yet)
- `main.py` launching a blank libadwaita `Adw.ApplicationWindow` with app id `com.iroddyan.Seru`
- Git repository initialized

**Acceptance:** `python -m seru` opens an empty, native-looking GNOME window.

---

## Bit 3 — Phase 2: Scanner & Database (build and test headless, no GTK dependency in this bit)

1. Read `anime_rename.py`'s parser first. Adapt its logic into `library/parser.py` — don't write a fresh parser from prose.
2. `scanner.py`: recursively walk the library root, identify anime folders and video files, call the parser for season/episode/title, detect movies vs episodes.
3. `media/ffprobe.py`: subprocess-based metadata extraction (arg list, never shell), called only for new/changed/metadata-missing files.
4. `database/`: SQLite schema with tables for `anime`, `episodes`, `media_files`, `library_locations`. Use normalized paths and stable IDs, not hardcoded absolute-path assumptions. (No `watch_progress`/resume-position table for now — see Bit 5's `launches` table instead.)
5. On rescan, remove stale DB rows for files that no longer exist on disk.
6. Every step wrapped in `try/except`; unparseable files marked `Unknown / Needs Review`, scan continues regardless.
7. Expose this as a CLI entry point (e.g. `python -m seru.library.scan`) so it can be tested against the real library with no UI involved yet.

**Acceptance:** running the CLI scanner against the real library produces title/episode/movie counts roughly matching `anime_smart_list.sh`'s output, and a second run (no files changed) is fast and doesn't re-probe anything.

---

## Bit 3b — Parser & Scanner Re-sync (required before Bit 4)

Context for Codex: the library has grown since the last scan, and `anime_rename.py`/`anime_smart_list.sh` have both been rewritten with logic the original port may not have captured. Don't build UI on top of a stale index.

1. Re-read the **current** `anime_rename.py` and `anime_smart_list.sh` in full — don't rely on a summary from an earlier session.
2. Update `library/parser.py` so it explicitly handles: the optional season token for absolute-numbering shows, per-(show, folder) forced-movie overrides, and the `_Needs Manual Sorting` folder exclusion — all as described in Bit 0.
3. Delete the old disposable test database and re-run a full scan against the library's current state (it has more files now than the 1,938 from Bit 3).
4. Skip whole-library number-matching against `anime_smart_list.sh` — its counting method is a different, cruder heuristic (see Bit 0) and isn't a reliable target to hit exactly. Instead, spot-check by hand:
   - Bleach: expect 200 episodes, no season-token conflicts.
   - Bleach; Thousand-Year Blood War: expect 41 episodes.
   - Jujutsu Kaisen: confirm the Season 4 file classifies as a movie, not an episode.

**Acceptance:** all three spot checks above pass against the real, current library. Don't move on to Bit 4 until they do.

---

## Bit 4 — Phase 3: Minimal Library UI

*(Depends on Bit 3b's re-synced index, not the original Bit 3 scan.)*

- Sidebar with **just** a "Library" section for now (not the full six-item nav from the original spec — that comes back once Watching/Statistics/etc. actually exist).
- Library page: list/grid of anime read from SQLite (not a live filesystem read).
- Anime detail page: title, stats, episode list.
- A basic search entry filtering the visible list (full filter-language search stays deferred).
- Wire "rescan" through `threading.Thread` + `GLib.idle_add` so triggering it from the UI never freezes the window.

**Acceptance:** matches the original spec's success mockup for Library + Detail — browse titles, click into e.g. Bleach, see its episode list.

---

## Bit 5 — Phase 4: Playback

- `media/player.py`: a small `PlayerBackend` abstraction (a `Protocol` or ABC is enough) with one implementation, `CelluloidBackend`, using `subprocess.Popen(["celluloid", str(path)])` — never a shell string.
- Wire the ▶ control on the episode list to it.
- Add a `launches` table (`anime_id`, `episode_id`, `timestamp`) and insert a row every time ▶ is pressed — this is the only "progress" data Seru records for now, and it's what Bit 10's Home page reads from later. Do not try to read Celluloid/mpv's own resume state.

**Acceptance:** clicking ▶ on a real episode launches Celluloid → mpv → the episode plays, and a row lands in `launches`.

---

## Bit 6 — MVP Checkpoint

Stop here and confirm Bits 1–5 all actually hold up against the real 2,000+ file library before writing anything below. This is the point to decide whether Python + PyGObject is holding up the way you hoped, before investing further.

---

## Bit 7 — Phase 5: Statistics

Port `anime_smart_list.sh`'s existing computations — total titles, episodes, movies, storage size, codec/resolution breakdown, screen-time estimate — into a Statistics page. This is pure aggregation over data the Bit 3 scanner already collected; no new scanning or external integration needed. Add "📊 Statistics" back into the sidebar nav.

**Acceptance:** numbers roughly match `anime_smart_list.sh`'s own report against the same library state.

---

## Bit 8 — Phase 6: Watching & Downloads (folder-driven views)

Add "👀 Watching" and "📥 Downloads" to the sidebar as filtered views over the Library data, keyed off the existing on-disk folder categories (e.g. `Watching - Finished/Unfinished Downloads`, `Downloads & Unorganized`) — detected the same configurable way Library detection already works, not hardcoded. These are **not** per-episode progress tracking; they're just "which top-level category is this title currently filed under."

**Acceptance:** a title you'd manually call "currently watching" (because of which folder it's in) shows up under Watching; unsorted downloads show up under Downloads.

---

## Bit 9 — Phase 7: Favorites

A simple per-anime boolean flag in Seru's own database (not derived from the filesystem), with a toggle on the anime detail page and a "⭐ Favorites" nav section filtering to flagged titles.

**Acceptance:** flagging a title in the detail page makes it appear under Favorites and persists across restarts.

---

## Bit 10 — Phase 8: Home / Dashboard

Add "🏠 Home" to the sidebar. Surfaces:
- **Continue Watching:** most recent entries from the `launches` table (added in Bit 5), grouped per anime
- **Recently Added:** latest scanner entries by discovery date
- **Library totals:** reuse Bit 7's aggregation queries

Build this last — it's the section most dependent on the others already having real data to show.

**Acceptance:** matches the original spec's Home mockup reasonably well, using only data the app already collected in earlier bits.

---

## Deferred — write these as their own separate bits later, once Bits 1–10 are solid

- Diagnostics (port `anime_smart_list.sh --doctor`)
- Polish: keyboard shortcuts, empty states, toasts, theming, accessibility labels, first-run setup
- Filesystem watcher (auto-rescan on change)
- True per-episode resume/progress tracking, if you ever decide the `launches`-table approach isn't enough
- Everything in the original "do not implement" list: embedded mpv, online metadata/artwork, auto-rename/organize, torrents, streaming, accounts, cloud sync, social, recommendations, subtitle downloading, mobile
