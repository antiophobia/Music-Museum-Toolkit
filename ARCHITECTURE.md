# Music Museum Toolkit Architecture

## Responsibilities

- `Scripts/archive.py` orchestrates a complete or resumed sync and prints reports.
- `Scripts/spotify_api.py` authenticates, retrieves playlist pages, classifies every
  entry, and converts supported tracks to source artifacts.
- `Scripts/collection_manager.py` merges artifacts into the permanent collection,
  assigns stable Museum IDs, validates preservation rules, and saves atomically.
- `Output/playlist_sync.json` stores snapshot, resume, and classification state.
- `Output/collection.checkpoint.csv` stores recoverable page progress.
- `Output/collection.csv` is the permanent source of truth.

## Playlist retrieval flow

1. Load the permanent collection, checkpoint, and JSON sync state.
2. Fetch the playlist name, snapshot ID, and Spotify-reported item total.
3. Resume the same snapshot or restart page scanning when the snapshot changed.
4. Request pages of up to 50 entries, including tracks and episodes.
5. Classify every returned entry before merging supported unique tracks.
6. Atomically checkpoint the accumulated collection and report after every page.
7. After the complete scan, build and validate the candidate collection.
8. Atomically replace the permanent CSV only when it changed and validation passed.
9. Remove the checkpoint and atomically record the completed snapshot and report.

A completed snapshot shortcut is used only when a saved detailed report exists.
This lets the first v0.3.1 run rescan an older completed snapshot to establish the
missing-entry accounting.

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

Category counts sum to the number of entries scanned. Counts and seen IDs are part
of resume state, so an interrupted scan keeps accurate whole-playlist accounting.

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
write completes. Page checkpoints never replace the permanent CSV. Rate limits,
interruptions, incomplete scans, malformed data, and validation failures therefore
cannot turn a partial result into the permanent collection.
