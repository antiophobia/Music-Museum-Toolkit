# Music Museum Toolkit Architecture

## Responsibilities

- `Music Museum Toolkit.bat` anchors the working directory at the repository root
  and starts the application menu on Windows. It pauses when Python returns an
  unexpected nonzero exit code.
- `Scripts/main.py` owns the user-facing menu. It dispatches one preservation run
  to `archive.main()`, shows the restoration placeholder, and returns control to
  the menu after either action.
- `Scripts/archive.py` orchestrates a complete or resumed sync and prints reports.
- `Scripts/spotify_api.py` authenticates, retrieves playlist pages, classifies every
  entry, converts supported tracks to source artifacts, and emits occurrence rows.
- `Scripts/collection_manager.py` merges artifacts into the permanent collection,
  assigns stable Museum IDs, validates preservation rules, and saves atomically.
- `Scripts/manifest_manager.py` owns the occurrence manifest schema, Museum ID
  mapping, validation, checkpointing, unchanged detection, and atomic saving.
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
