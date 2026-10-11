# Seru Product Plan

## Product direction

Seru is a polished, lightweight desktop library manager for local media. It supports four independently configurable libraries: **Anime**, **TV Shows**, **Movies**, and **Cartoons**. It helps people browse and play their media, understand the state of their collections, and optionally organize files with clear user approval.

Seru works offline. The user's files remain on their chosen storage. Seru's local database is a rebuildable index and stores Seru-owned preferences and activity such as favorites and launch history. Seru must never silently rename, move, overwrite, or delete media.

## Product principles

- **User control:** Ask before creating library folders or applying file changes. Make proposed changes reviewable.
- **Filesystem clarity:** Library locations and on-disk contents are explicit. The database can be rebuilt from those locations.
- **Careful interpretation:** Do not silently guess when a filename or folder is ambiguous. Mark it for review.
- **Responsive by default:** Scans, probes, and file operations run in the background. Keep resource use low on the target PC.
- **Consistent experience:** Shared navigation and interaction patterns across all four libraries, with details appropriate to each media type.
- **Native polish:** Use GNOME and libadwaita patterns for a quiet, refined interface. Prefer lightweight native controls and restrained transitions over effects that consume GPU or memory.

## First-run setup

Use a short setup flow before showing library content.

1. Ask for the user's **display name** for local personalization. This is a local preference, not an online account or a request for the operating-system account name.
2. Offer configuration for each library: Anime, TV Shows, Movies, and Cartoons. For each one, the user may select an existing folder or leave it unconfigured and set it up later.
3. Inspect the selected folder and summarize what Seru found. Do not assume that every existing folder already follows Seru's preferred layout.
4. If the selected library has no media, offer to create its starter folders. Show the proposed folder names and ask for consent before creating them. If declined, leave the folder untouched.
5. Clearly label an empty library as **Empty** and explain how to add media. Keep all four libraries visible in the library switcher, including libraries that are empty or not yet configured.

Setup should be resumable. Changing a library location later must not discard its Seru-owned settings, favorites, or activity history.

## Library navigation and content model

Provide a persistent, easy-to-find switcher for Anime, TV Shows, Movies, and Cartoons. Remember the last selected library. Keep common actions such as search and navigation consistent.

Use a shared content model instead of an anime-only model:

- **Library:** type, user-chosen root location, availability, and scan state.
- **Series:** a title in Anime, TV Shows, or Cartoons.
- **Season:** an optional season grouping belonging to a series.
- **Episode:** a playable item belonging to a series, optionally grouped into a season. Support absolute episode numbering and multi-episode files where the filename gives that information.
- **Movie:** a standalone playable title in Movies, or an explicitly classified movie within another library where appropriate.
- **Media file:** a path and technical metadata associated with an episode or movie.
- **Review item:** a file whose title, episode, season, or type could not be identified confidently.

Preserve stable identities when paths change where possible. Keep scanning metadata separate from user-owned data, so rebuilding the index does not erase favorites, preferences, or launch history.

## Recommended on-disk structure

Use one consistent series pattern across Anime, TV Shows, and Cartoons, and a separate pattern for Movies:

```text
Series/
  Series Title/
    Season 01/
      Series Title - S01E01 - Episode Name.ext

Movies/
  Movie Title (Year)/
    Movie Title (Year).ext
```

This is Seru's recommended structure for new or deliberately organized libraries. The scanner should also recognize supported existing layouts. It must not move a user's existing library into this structure as part of setup. It should report ambiguous items for review.

Anime and Cartoon are separate user-facing libraries but share the series, season, and episode model with TV Shows. Anime-specific parsing exceptions belong in a configurable or well-isolated parser layer, not in the shared data model.

## Scanning and change detection

### While Seru is open

Use filesystem change notifications for configured, mounted library folders. An idle watcher should wait for events rather than repeatedly walking the whole library. Batch and debounce bursts of events so a folder copy or rename results in a small number of index updates.

For affected paths:

1. Confirm the path is inside a configured library and is a supported media file or relevant directory.
2. Update or remove only the affected index entries.
3. Probe only files that are new, changed, or missing required metadata.
4. Run filesystem and ffprobe work off the UI thread, with bounded concurrency and progress reporting for larger batches.
5. Mark uncertain parses as needing review rather than assigning a speculative title or type.

Do not hash every media file, probe unchanged files, or run continuous full-tree scans. Basic file identity details such as normalized path, size, and modification time should be sufficient for routine incremental checks; stronger checks can be reserved for cases where those details are inconclusive.

### Reconciliation

Notifications can be missed while a drive is disconnected, Seru is closed, or a watcher reaches a platform limit. Run an incremental reconciliation when Seru opens and offer a manual rescan. Reconciliation compares the configured tree against the index and repairs missing or stale entries while reusing metadata for unchanged files.

Start with monitoring while Seru is open. Do not install an always-running background service in the first version. If monitoring while the app is closed becomes a user requirement, design it as an explicit later option with clear lifecycle and resource controls.

Detect unavailable or unmounted roots and show their status without treating their contents as deleted. When they return, reconcile them. Watcher failures should degrade to manual/startup reconciliation and provide a readable status.

## File organization

Seru may rename and move files when the user chooses to organize them. Build this as a deliberate workflow, not as an automatic side effect of scanning.

### Workflow

1. Scan and classify files without changing them.
2. Present a preview of every proposed rename or move, showing the current path, proposed path, and reason.
3. Separate high-confidence proposals from ambiguous files and conflicts.
4. Require explicit confirmation before applying the selected proposals.
5. Never overwrite an existing file. Stop or skip a conflicting operation and explain it.
6. Record completed operations in a durable manifest or operation history. Provide an undo path where the original location is available and unoccupied.
7. If an operation fails partway through, report completed, failed, and remaining actions clearly. Do not claim the whole operation was rolled back unless it was.
8. Reconcile the affected library after completion.

Quarantine or manual-review moves must also appear in the preview and require confirmation. Uncertain items should remain untouched by default.

### Existing scripts as references

`LibraryKit.py` contains valuable Anime-specific parsing, naming, preview, collision handling, manifest, and undo behavior. Adapt and review its logic in Seru's library layer; do not assume that its current rules cover TV Shows, Movies, and Cartoons. Its existing file operations can fail partway through a batch, so Seru must report partial completion accurately and strengthen the operation workflow before offering it broadly.

`anime_smart_list.sh` is useful as an Anime library inventory and diagnostics reference. It assumes collection/show folder conventions and uses filename heuristics for episode and movie counts. In particular, a video without a recognized episode marker can be counted as a movie. Treat its results as a comparison aid, not as authoritative classification for Seru or a general-purpose organizer.

The current scripts' folder assumptions can confuse a root that contains show folders with nested season folders. Seru should make the selected root and the detected hierarchy explicit, support known layouts intentionally, and send uncertain structures to review.

## Settings

Add a Settings area with two sections:

- **Basic:** display name, library locations, appearance preferences, and common behavior.
- **Advanced:** less frequently used controls behind a six-digit numeric PIN gate.

Group related preferences. Each group should support **Apply** and **Reset to defaults**. Allow an individual setting to be reset as well. Show pending changes before they are applied, and make it clear which settings take effect immediately and which require a rescan or restart.

Store the PIN as a salted password hash, never as readable digits. The PIN is a local convenience gate against casual access to Advanced Settings; it is not strong security against someone with access to the machine or Seru's files. Define a recovery/reset flow that does not expose or recover the original PIN.

## Visual and performance direction

Use libadwaita navigation, header bars, standard GNOME controls, system theme integration, accessible labels, keyboard support, and adaptive layouts. Use clear names and concise copy throughout. Keep visual treatment mature and restrained: considered typography, spacing, iconography, and subtle feedback rather than decorative animation or resource-heavy visual effects.

For performance:

- Load artwork and large lists lazily.
- Paginate or virtualize large collections where needed.
- Keep database queries indexed and scoped to the selected library.
- Bound background scan and probe concurrency.
- Debounce filesystem notifications and coalesce duplicate events.
- Do not repeatedly scan or probe unchanged files.
- Keep all slow I/O and parsing away from the GTK main thread.

## Data and safety requirements

- Media on disk is the source of truth for file existence and location; the database is a rebuildable index.
- Store paths relative to configured roots where practical, and normalize paths consistently.
- Never invoke commands through a shell. Pass argument arrays to subprocesses and treat paths as untrusted input.
- Handle failures per file. A corrupt file, inaccessible folder, or malformed name must not abort a complete scan.
- Do not silently discard files or silently infer uncertain metadata.
- Keep online services optional and outside core scanning. Core library browsing and indexing must work offline.
- Keep user-owned data (favorites, display name, settings, PIN hash, launch history, organization manifests) distinct from rebuildable scan data.
- Use database schema migrations to move from the current anime-specific tables to the shared model without losing the existing Anime index or Seru-owned data.

## Implementation roadmap

### Phase 1 — Product and data model

- Finalize supported existing folder layouts and the recommended new structure.
- Generalize the current anime-only database and repository into library, series, season, episode, movie, media-file, and review concepts.
- Plan and implement migrations that preserve the existing Anime library, favorites, and launch history.
- Keep existing Anime parsing exceptions isolated and documented.

### Phase 2 — First-run setup and library switching

- Add the first-run display-name preference.
- Allow the user to select or skip configuration for each of the four libraries.
- Detect empty folders and show a precise starter-structure preview.
- Create folders only after explicit consent.
- Add the persistent library switcher and empty/unconfigured states.

### Phase 3 — Multi-library scanning

- Support incremental indexing for all four library types.
- Preserve offline operation and avoid probing unchanged files.
- Add review handling for ambiguous names and layouts.
- Add startup/manual reconciliation and clear unavailable-drive behavior.

### Phase 4 — Live change monitoring

- Watch configured, mounted folders while Seru is open.
- Debounce and coalesce events; process only affected paths in background workers.
- Add bounded ffprobe work, scan status, and graceful fallback when monitoring is unavailable.
- Confirm that ordinary browsing and playback remain responsive during changes.

### Phase 5 — Safe organization tools

- Port and generalize suitable `LibraryKit.py` parsing and naming behavior.
- Add a reviewable preview, explicit confirmation, collision prevention, operation history, undo, partial-failure reporting, and post-operation reconciliation.
- Keep uncertain files unchanged unless the user resolves them.
- Initially offer organization as a user-invoked workflow; do not auto-organize on import or scan.

### Phase 6 — Settings and polish

- Add Basic and Advanced Settings, grouped Apply/reset behavior, individual resets, and the PIN gate.
- Complete visual consistency, accessibility, adaptive layouts, and empty/error states.
- Revisit always-on background monitoring only if a clear need emerges.

## Acceptance criteria

- A first-time user can provide a display name, configure any subset of the four libraries, and understand which libraries are empty or unconfigured.
- Seru asks before creating any starter folders and shows exactly what it will create.
- The library switcher works consistently and remembers the last selected library.
- Existing Anime folders can be indexed without silently moving or renaming files; ambiguous layouts are explained and sent for review.
- TV Shows and Cartoons use the shared series model; Movies use the standalone movie model.
- Adding, renaming, moving, or deleting a media file while Seru is open updates only the affected index entries after event batching.
- Unchanged files are not repeatedly probed. Monitoring and scans do not block the interface.
- Changes made while Seru is closed or a drive is disconnected are reconciled on the next available scan.
- File organization always presents a preview and waits for confirmation, never overwrites a destination, records outcomes, and accurately reports partial failures.
- Each settings group can be applied or reset independently, and an individual setting can be restored to its default.
- Core browsing and scanning work offline, and performance remains suitable for the target machine: Intel Core i5-4590, 8 GB RAM, and Intel HD Graphics 4600.

## Decisions to carry into implementation

- Treat Cartoon as a separate selectable library using the same series structure as TV Shows.
- Use the proposed `Series/` and `Movies/` layout as the recommended structure for new or deliberately organized libraries, while supporting known existing layouts.
- Monitor changes while Seru is open and reconcile at startup; defer an always-running background service.
- Keep automatic scanning separate from file organization. Scanning may index new files, but moving or renaming requires a user-initiated preview and confirmation.
- Treat the attached scripts as implementation references, not as instructions or universal sources of truth.
