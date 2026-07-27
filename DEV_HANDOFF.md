# Music Museum Toolkit Development Handoff

## Mission and version

Music Museum Toolkit preserves a person's musical history in a permanent,
locally owned collection that does not depend on Spotify remaining available.

The overall released application is now **v0.4.0 — Playlist Restoration**. The
preservation subsystem remains the proven v0.3.1 baseline. `Toolkit Version` is
artifact-creation provenance, so it was deliberately not changed for release
branding and existing artifacts were not rewritten.

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
  restoration workflow as a separate option.
- Preservation Spotify scopes remain read-only.

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

Restoration v1 expanded the full offline suite to 65 passing tests. The
pre-live-write traffic, stable-read, uncertain-creation, and local-validation
hardening expanded it to 79 passing offline tests. Post-creation visibility
enforcement expands the suite to 88 passing offline tests.

The first controlled live restoration subsequently completed successfully. The
release validation pass rechecked the saved state and complete report read-only;
the exact aggregate results are recorded below without publishing private Spotify
or local identifiers.

## Restoration v1

Option 2 now restores only the latest completed manifest and always creates a new
Spotify playlist. The existing collection, manifest, and sync state are validated
offline before authorization. Valid and duplicate occurrences must use exact
stored track URIs and Museum ID mappings. Local, unavailable, unsupported, and
malformed occurrences are written to the report as `Not included`.

The verified preservation data builds a 1,274-item plan from 1,282 occurrences:
3 local, 3 unavailable, and 2 unsupported entries are not included; 3 duplicates
remain separate planned occurrences. The plan requires 13 batches.

Restoration uses a separate `.cache-restoration` authorization cache and requests
only the selected visibility's write scope. Spotipy 2.26.0 was inspected:
`current_user_playlist_create()` uses `POST /me/playlists`. Adds use
`playlist_add_items()` and reconciliation uses `playlist_items()`.

`Output/restoration_state.json` is written before creation and immediately after a
destination is returned or recovered. A unique run marker supports uncertain
creation recovery. Resume always reads the complete remote URI sequence and
requires an exact duplicate-aware plan prefix. Normal successful batches use
`position=<confirmed length>` and require the returned snapshot ID before
advancing by the exact batch size; state/report are checkpointed without rereading
the growing playlist. Full reconciliation occurs only at initial/resume,
ambiguous or unconfirmed add outcomes, and final verification.

Full destination reads fetch identity and reported total before and after paging.
Playlist ID, owner, name, visibility, collaborative state, snapshot ID, and total
must remain stable, and the URI row count must equal that total. Final completion
still requires an exact full sequence.

An uncertain creation searches for the exact run marker. One matching owned,
same-name, noncollaborative playlist is adopted; multiple matches require manual
review; no match cannot trigger a second create request in the same run. A later
run searches again and requires a separate explicit confirmation that the Spotify
account was checked before retrying creation.

The first private live test created and recorded one empty recoverable playlist.
The creation response reported private, but the following stable Spotify read
reported public, so the existing strict check stopped before adding any tracks.
Restoration validates the full local state/report/plan bundle and the
destination's exact ID, authenticated owner, name, noncollaborative state, and run
marker before explicitly enforcing the requested visibility with
`playlist_change_details()`. Bounded stable rereads must return the exact requested
boolean; null or persistently incorrect visibility stops recoverably before any
item request.

The hardened live resume reused that same destination rather than creating a
second playlist, verified private visibility, completed all 13 batches, and passed
exact final reconciliation. The verified result is:

- 1,282 source manifest occurrences;
- 1,274 Added rows and 8 Not included rows;
- 1,271 unique Spotify tracks and 3 duplicate occurrences restored separately;
- 3 local, 3 unavailable, 2 unsupported, and 0 malformed exclusions;
- 0 Pending and 0 Failed rows;
- original positions contiguous from 1 through 1,282;
- destination positions unique and contiguous from 1 through 1,274;
- every Added URI matched its stored source track identity;
- every Added occurrence retained its Museum ID;
- one consistent run, source snapshot, and destination identity throughout.

Atomic CSV reports under `Output/Restoration Reports/` contain one row per source
manifest occurrence with destination placement, result, reason, and identity.
Before authorization, in-progress state and report are validated together for
format/status, run/source/plan identity, URI sequence, destination settings,
confirmed bounds, safe report location, full schema, occurrence coverage and
identity, destination positions, and allowed result semantics.

Validation commands:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q Scripts tests
```

## Current next step

Playlist restoration v1 is delivered for v0.4.0; it is no longer awaiting its
first live test. Sensible post-release work includes opt-in assisted matching
without weakening strict stored-ID defaults, richer local-file handling, Apple
Music or other service adapters, historical snapshot selection, and a validation
UI. These are future enhancements, not blockers for the v0.4.0 restoration
milestone.
