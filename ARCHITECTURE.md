# Music Museum Toolkit Architecture

## System overview

Music Museum Toolkit implements a complete preservation and reconstruction loop:

```text
Spotify source playlist
    -> read-only preservation
    -> permanent Collection + latest occurrence manifest
    -> deterministic restoration plan
    -> new Spotify destination playlist + permanent restoration report
```

The records have deliberately separate ownership:

- **Collection** (`Output/collection.csv`): one permanent row per unique Spotify
  artifact, including its stable Museum ID and preserved metadata.
- **Playlist manifest** (`Output/playlist_manifest.csv`): one ordered row per
  occurrence in the latest completed source snapshot, including duplicates and
  exclusions.
- **Restoration plan**: the deterministic ordered URI sequence derived only from
  valid and duplicate manifest rows after Collection mapping validation.
- **Restoration state** (`Output/restoration_state.json`): the atomic,
  resumable write-side checkpoint for one run-bound destination.
- **Restoration report** (`Output/Restoration Reports/*.csv`): the permanent
  outcome for every source occurrence, whether added or not included.

## Responsibilities

- `Music Museum Toolkit.bat` anchors the working directory at the repository root
  and starts the application menu on Windows. It pauses when Python returns an
  unexpected nonzero exit code.
- `Scripts/main.py` owns the user-facing menu. It dispatches one preservation run
  or one restoration workflow and returns control to the menu.
- `Scripts/archive.py` orchestrates a complete or resumed sync and prints reports.
- `Scripts/spotify_api.py` authenticates, retrieves playlist pages, classifies every
  entry, converts supported tracks to source artifacts, and emits occurrence rows.
- `Scripts/collection_manager.py` merges artifacts into the permanent collection,
  assigns stable Museum IDs, validates preservation rules, and saves atomically.
- `Scripts/manifest_manager.py` owns the occurrence manifest schema, Museum ID
  mapping, validation, checkpointing, unchanged detection, and atomic saving.
- `Scripts/restore_playlist.py` owns the guided restoration workflow, confirmation,
  Spotify operation sequencing, and terminal reporting.
- `Scripts/restoration_manager.py` owns restoration planning, strict identity
  validation, plan hashing, atomic state/report persistence, prefix
  reconciliation, and final sequence verification.
- `Scripts/spotify_api.py` keeps preservation authorization read-only and exposes a
  separate restoration authorization cache plus current playlist create, add,
  discovery, and read operations.
- `Output/playlist_sync.json` stores snapshot, resume, and classification state.
- `Output/collection.checkpoint.csv` stores recoverable page progress.
- `Output/playlist_manifest.checkpoint.csv` stores recoverable occurrence rows.
- `Output/collection.csv` is the permanent source of truth for unique artifact
  identity and metadata.
- `Output/playlist_manifest.csv` is the source of truth for occurrence order and
  classification in the most recently completed playlist snapshot.

`archive.py` is import-safe: importing it does not start a sync. Its callable
`main()` is used by the application menu, while its `if __name__ == "__main__"`
guard preserves direct execution with `python Scripts\archive.py`.

## Playlist retrieval flow

1. Load the permanent collection, checkpoint, and JSON sync state.
2. Fetch the playlist name, snapshot ID, and Spotify-reported item total.
3. Resume the same snapshot or restart page scanning when the snapshot changed.
4. Request pages of up to 50 entries, including tracks and episodes.
5. Classify every returned entry, emit one ordered manifest row, and merge
   supported unique tracks.
6. Atomically checkpoint manifest rows, the accumulated collection, and resume
   state after every page.
7. After all pages are checkpointed, fetch the playlist summary again. Playlist
   ID, name, snapshot ID, and reported total must still match the initial summary.
8. Require entries scanned, manifest row count, and the stable Spotify-reported
   total to be equal, with classification totals also equal to entries scanned.
9. Only after stable and complete verification, build the candidate collection and map
   valid and duplicate occurrences to permanent Museum IDs.
10. Validate both candidate outputs before replacing either permanent file.
11. Atomically save each individual file, skipping unchanged outputs.
12. Remove both checkpoints and atomically record the completed snapshot only
    after both permanent saves succeed.

If final verification detects a changed playlist, is rate-limited, is interrupted,
or fails for another API reason, neither permanent output is saved and completion
is not recorded. Completed pages and in-progress state remain recoverable. A
changed snapshot, name, or total makes the next run reject the old resume context
and start a clean occurrence scan.

If the stable summary exposes an incomplete occurrence scan, permanent outputs are
left untouched and the unusable checkpoints/state are invalidated so the next run
starts at position one rather than reusing an offset beyond the playlist total.

A completed snapshot shortcut is used only when a saved detailed report and a
valid permanent manifest match the live playlist and snapshot. A legacy completed
state without a matching manifest forces one full scan to establish it.

## Item classification

Each scanned entry belongs to exactly one category:

- **valid track**: a non-local Spotify track with a nonblank string ID, first
  occurrence in this scan;
- **duplicate occurrence**: another occurrence of a valid track ID already seen;
- **local file**: Spotify marks the item `is_local`;
- **unavailable entry**: the entry explicitly contains a null track/item;
- **unsupported entry**: the item is an episode or another non-track type;
- **malformed entry**: wrong structure, missing item field, non-dictionary item, or
  a Spotify track without a usable ID.

Category counts sum to the number of entries scanned. Counts are part of resume
state, and the checkpoint manifest's valid-track positions are the authoritative
record of first-seen source IDs. No separate `seen_track_ids` resume state is kept.

## Playlist manifest

Manifest version 1 contains:

`Manifest Version`, `Playlist ID`, `Playlist Name`, `Snapshot ID`, `Captured At`,
`Playlist Position`, `Classification`, `Restorable`, `Museum ID`,
`Source Track ID`, `Spotify URI`, `Title`, `Artist`, `Album`, `Added At`,
`Duplicate Of Position`, and `Reason`.

Positions are one-based, unique, contiguous, and ordered exactly as returned by
Spotify. A first usable Spotify track is `valid track`; later occurrences are
`duplicate occurrence` rows linked backward to the first position. Both are
restorable and map to the same Museum ID. Local, unavailable, unsupported, and
malformed rows are nonrestorable, retain safe returned metadata, and explain the
reason without inventing missing values.

Permanent validation reconciles row count and classification totals with the scan
report; checks schema, positions, playlist/snapshot identity, and capture identity;
rejects unknown categories or invalid restorable flags; verifies collection
mappings; and checks duplicate linkage.

Before resume, checkpoint validation independently requires the full schema and
manifest version; matching playlist, name, and snapshot identity; one nonblank,
consistent capture timestamp; numeric whole, unique, ordered, contiguous
positions; allowed classifications and Restorable values; correct backward
duplicate links; and row/classification totals matching the saved in-progress
report. Invalid resume data is ignored and the current snapshot starts clean.

## Artifact identity

`Museum ID` is the permanent internal identity. It must match `MMT-` plus six
digits, is never renumbered, and is never reused. `Source Track ID` is external
Spotify identity; preserved Spotify rows must have unique, nonblank source IDs.
New IDs start above the greatest existing valid Museum ID.

Required identity fields are Source, Source Track ID for Spotify rows, Title,
Artist, and Album. Popularity is metadata, not identity.

## Timestamp and version semantics

`Archived At` means first preservation time. It never changes during metadata
refreshes. `Toolkit Version` likewise means the version that first created the
artifact. Existing `0.2` values remain historically correct; new v0.3.1 artifacts
receive `0.3.1`. The schema is unchanged.

The complete application release is v0.4.0 — Playlist Restoration. That release
label does not retroactively rewrite artifact provenance or change the v0.3.1
preservation subsystem's creation-version semantics.

## Validation before save

Before permanent replacement, validation rejects:

- empty results;
- missing schema columns or required identity fields;
- missing, malformed, or duplicate Museum IDs;
- missing or duplicate Spotify source track IDs;
- removal of any previously preserved source ID;
- changes to an existing Museum ID, `Archived At`, or Notes.

Failure raises an error before the permanent-save function is reached. The existing
collection remains untouched.

## Metadata and idempotency

Playlist metadata may refresh title, artist, album, release date, duration,
popularity, and URL. Missing optional values do not erase preserved nonblank
values. Notes always remain user-owned. A candidate identical to the saved
collection is not rewritten. Equality uses a comparison-only canonical view that
normalizes CSV dtype, blank/null, column order, row order, and index differences;
the stored collection and candidate are not mutated by this comparison.

Popularity is read when present in Spotify's playlist item payload. The initial
live archive contained blanks because that payload did not populate the field, not
because the toolkit filtered those tracks. Blank popularity is always safe.

## Atomic and checkpoint safety

CSV and JSON writes go to a sibling `.tmp` file and use `os.replace` only after the
write completes. Each file replacement is atomic, but replacing `collection.csv`
and `playlist_manifest.csv` is not one filesystem transaction. Both candidates are
validated before either save, the collection is saved first, and completed state
is written only after both individual saves succeed. If collection saving succeeds
but manifest saving fails, the old permanent manifest and in-progress checkpoints
remain; the next run can reconcile and complete safely.

Page checkpoints never replace permanent outputs. Rate limits, interruptions,
incomplete scans, snapshot races, malformed data, validation failures, and write
failures cannot turn a partial manifest into the permanent manifest.

Playlist summary requests explicitly include Spotify's `id` field so final
playlist-ID verification normally uses the returned identity.

## Playlist restoration flow

1. Load the permanent collection, latest permanent manifest, and completed sync
   state without contacting Spotify.
2. Apply existing collection and manifest validation and require the manifest
   snapshot to equal `complete_snapshot`.
3. Build an exact ordered plan from `valid track` and `duplicate occurrence`
   rows. Every planned URI must be exactly `spotify:track:<Source Track ID>` and
   map to the stored Museum ID. No substitutions are allowed.
4. Report every nonrestorable occurrence without adding it to the plan.
5. Collect destination name and visibility, then require explicit final
   confirmation before authorization.
6. Atomically persist planned state and a full occurrence report.
7. On resume, validate the state version/status, run and source identity, exact
   plan hash and URI sequence, destination settings, confirmed bounds, report
   location/schema, every occurrence identity and destination position, and all
   report results before authorization.
8. Authenticate through `.cache-restoration` with existing read scopes plus only
   the write scope required by the selected visibility.
9. Create a new playlist with `current_user_playlist_create()` and a unique run-ID
   marker. The deprecated `user_playlist_create()` endpoint is never used.
10. Persist returned destination identity immediately. An uncertain creation is
    recovered only through exactly one current-user playlist carrying the run ID.
    No match prevents another creation request in that run; a later retry requires
    separate confirmation after the user checks the Spotify account.
11. Read the destination stably and validate immutable identity before any details
    mutation: exact playlist ID, authenticated owner, saved name,
    `collaborative=false`, and the exact current restoration run marker.
12. If Spotify does not report the requested visibility boolean, explicitly call
    `playlist_change_details()` with the requested `public` value and
    `collaborative=false`. Use a bounded number of stable rereads to require the
    exact boolean; `public=null` is never accepted as private.
13. Only after visibility is verified, require the complete destination URI
    sequence to be an exact prefix of the deterministic plan.
14. Add at most 100 URIs with `playlist_add_items()`, explicitly placing each
    batch at the confirmed length. A successful response must contain a usable
    snapshot ID; that response advances the exact batch length and atomically
    checkpoints state/report without a full playlist reread.
15. Perform a full prefix reconciliation only before resume/initial writing,
    after ambiguous outcomes, or when a nominal success lacks a snapshot ID.
    Deterministic rejections stop with the attempted batch reported as blocked.
16. Mark completion only after destination ownership, item count, and the complete
    ordered URI sequence match exactly.

Restoration always creates a new playlist. It never edits, replaces, removes from,
or deletes an existing playlist. A partial destination is recoverable state, not
rollback material.

Every full destination read is snapshot-stable: identity, owner, name, visibility,
collaborative state, snapshot ID, and reported total are fetched before and after
item pagination. All values must remain unchanged, and returned URI rows must equal
the stable total. An unstable read is never used for prefix or completion
decisions. For the verified 1,274-item plan, the normal path uses 13 positioned add
requests, one initial empty/prefix reconciliation, and one final stable
reconciliation rather than rereading the growing playlist after every batch.

The first private live test observed a creation response reporting private
followed by a stable Spotify read reporting public. No items were added, and the
destination remained recoverable. Post-creation visibility enforcement handles
this platform discrepancy without weakening identity checks: visibility is
mutable only after the state/report/plan bundle and exact run-bound destination
pass validation. This is the **identity-before-mutation** guarantee. Exact
requested visibility must then be established before the first add request. This
is the **visibility-before-add** guarantee. Failures or inconclusive bounded
verification stop before any item add and never trigger another playlist creation
request.

`Output/restoration_state.json` records source snapshot/capture identity, run ID,
plan hash and URI sequence, destination identity, visibility, confirmed length,
remote snapshot, status, report path, and timestamps. Each atomic CSV report under
`Output/Restoration Reports/` contains one row per manifest occurrence, including
separate duplicate rows and all nonrestorable reasons.

## v0.4.0 live validation

The controlled live reconstruction completed on July 26, 2026. A 1,282-occurrence
manifest produced 1,274 ordered additions: 1,271 unique tracks and 3 duplicate
occurrences. Thirteen positioned batches completed. Eight source occurrences were
reported as not included (3 local, 3 unavailable, 2 unsupported, 0 malformed),
with no failed or pending report rows.

The hardened resume reused the existing recoverable destination from the
visibility discrepancy, verified it as private before adding, and finished with
exact contiguous source positions 1–1,282, destination positions 1–1,274, stored
URI identities, Museum ID mappings, and final remote sequence.
