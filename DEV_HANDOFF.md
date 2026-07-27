# Music Museum Toolkit Development Handoff

## Mission and version

Music Museum Toolkit preserves a person's musical history in a permanent,
locally owned collection that does not depend on Spotify remaining available.

The stable baseline remains v0.3.1. `Toolkit Version` is artifact-creation
provenance and was not changed for this unreleased manifest feature.

## Latest verified live state

The latest live preservation run reported 1,282 playlist entries and preserved
1,271 unique Spotify artifacts. It added 9 new artifacts and left 1,262 existing
artifacts unchanged.

The exhaustive classification was:

- 1,271 valid unique tracks;
- 3 duplicate occurrences;
- 3 local files;
- 3 unavailable entries;
- 2 unsupported entries;
- 0 malformed entries.

These categories total all 1,282 scanned entries.

## Source-of-truth ownership

- `Output/collection.csv` owns unique artifact identity and metadata. It retains
  stable Museum IDs, first archive timestamps, creation-version provenance, and
  user Notes.
- `Output/playlist_manifest.csv` owns occurrence order and classification for the
  most recently completed playlist snapshot. It records one row per returned
  entry, including duplicates and non-artifact entries.
- `Output/playlist_sync.json` owns completed/in-progress snapshot and report state.
- `Output/collection.checkpoint.csv` and
  `Output/playlist_manifest.checkpoint.csv` hold resumable page progress and never
  replace permanent output during a partial scan.

## Occurrence manifest implementation

`Scripts/spotify_api.py` retains its existing classification interface and adds an
occurrence-producing path. Each returned entry receives a one-based position and
one of six classifications: valid track, duplicate occurrence, local file,
unavailable entry, unsupported entry, or malformed entry.

`Scripts/manifest_manager.py` owns manifest version 1. Its schema is:

`Manifest Version`, `Playlist ID`, `Playlist Name`, `Snapshot ID`, `Captured At`,
`Playlist Position`, `Classification`, `Restorable`, `Museum ID`,
`Source Track ID`, `Spotify URI`, `Title`, `Artist`, `Album`, `Added At`,
`Duplicate Of Position`, and `Reason`.

Valid and duplicate occurrences are restorable when they have a usable Spotify
track ID. Duplicates retain their position, link backward to the first occurrence,
and map to the same permanent Museum ID. Nonrestorable rows preserve safe metadata
returned by Spotify and include an explanatory reason without invented values.

`Scripts/archive.py` checkpoints manifest rows after each page. Resume is accepted
only when the full checkpoint schema, manifest version, playlist identity, single
capture timestamp, whole/unique/contiguous positions, classifications, Restorable
values, duplicate links, row count, and classification totals match saved state.
A changed snapshot or inconsistent checkpoint starts a clean occurrence scan while
retaining the permanent collection and last completed manifest.

The checkpoint manifest's valid-track-to-first-position mapping is authoritative
for duplicate detection after resume. The redundant `seen_track_ids` field was
removed from `playlist_sync.json` writes so resume state cannot drift from
occurrence state.

After all pages are retrieved, archive orchestration fetches the playlist summary
again. Playlist ID context, name, snapshot ID, and reported total must match the
initial summary before either candidate is built or saved. A change, final-check
rate limit, interruption, or other verification failure preserves checkpoints,
does not replace either permanent output, and does not record completion.

After stable snapshot verification, a separate completeness gate requires
`playlist_entries_scanned`, manifest row count, and Spotify's stable reported total
to match exactly. Classification totals must also equal entries scanned. An
incomplete result cannot reach candidate construction or saving; its unusable
checkpoints and in-progress state are invalidated so the next run starts clean.
Local, unavailable, unsupported, and duplicate rows count as occurrences in this
reconciliation. Playlist summaries explicitly request Spotify's returned `id`.

After stable verification, orchestration builds and validates both candidates
before either save. Each permanent file replacement is atomic by itself; the two
files are not a single filesystem transaction. The collection saves first, the
manifest saves second, and completed state is recorded only after both succeed. If
the manifest save fails after the collection save, the prior permanent manifest
and in-progress checkpoint/state remain so the next run can reconcile safely.

If a completed legacy snapshot has no valid matching permanent manifest, the
shortcut is bypassed for one full scan. A matching valid manifest is validated and
not rewritten.

## Preserved v0.3.1 guarantees

- Museum IDs remain permanent, unique, and never renumbered.
- Existing artifacts cannot be removed.
- Archived At, Notes, and creation-version provenance remain immutable.
- Missing optional Spotify metadata cannot erase preserved nonblank values.
- Collection comparison remains semantic and unchanged collections are not
  rewritten.
- Classification accounting remains exhaustive and reconciled with scanned count.
- Collection and state writes remain atomic and resumable.
- `python Scripts\archive.py` remains supported and import-safe.
- `Scripts/main.py` still dispatches `archive.main()` exactly once and retains the
  restoration placeholder.
- Spotify scopes remain read-only; restoration and playlist creation are not
  implemented.

## Configuration and repository state

`Config/config.py` loads Spotify configuration from environment variables and the
project-root `.env` file. Existing system environment values take priority. `.env`
and Spotify OAuth cache files are excluded by `.gitignore`; `.env.example` remains
trackable. Credentials are not embedded in `Config/config.py`.

The project has a `.git` directory. No commit or push was made for this work.
Personal `Input`, `Output`, and `Logs` data remain ignored.

## Tests and verification

The pre-manifest suite had 20 passing tests, and the initial manifest suite had 32.
The final hardening suite now has 45 passing tests. It covers all previous behavior plus
stable and changed final snapshot verification, name/total/playlist-ID changes,
final-verification rate limits and failures, fractional/reordered/duplicate/gapped
checkpoint positions, capture timestamp consistency, checkpoint/report
reconciliation, invalid duplicate links, valid resume, and removal of stale
seen-track resume state. It also covers short stable pages, manifest/scanned-count
drift, classification-count drift, clean restart after invalidation, returned
playlist-ID requests, and complete scans containing non-artifact occurrences.

Validation commands:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q Scripts tests
```

## Current next step

Run one live read-only preservation scan to create and validate the first
`Output/playlist_manifest.csv`. Because the existing completed snapshot predates
the manifest, the toolkit will intentionally bypass the completed-snapshot
shortcut once. No Spotify write permission is needed.

After verifying the generated 1,282-row manifest against the latest snapshot, the
next development phase can design playlist restoration semantics. Before writing
to Spotify, decide whether restoration creates or updates a playlist, define
confirmation and rollback behavior, handle unavailable/local/unsupported entries,
and make write-side resume idempotent.
