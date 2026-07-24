# Music Museum Toolkit

**Preserve your music. Own your collection.**

Music Museum Toolkit turns a Spotify playlist into a permanent local collection.
Spotify supplies metadata, but `Output/collection.csv` remains the source of truth.

## Current version

**v0.3.1 — Validation and hardening**

## Run the toolkit

From the project directory on Windows 11:

```powershell
python Scripts\archive.py
```

The sync is incremental and resumable. Completed pages are checkpointed. The
permanent collection is replaced atomically only after the completed result passes
integrity and preservation validation.

## v0.3.1 behavior

- Every returned playlist entry is counted as a valid unique Spotify track,
  duplicate occurrence, local file, unavailable/null entry, unsupported item, or
  malformed entry.
- The final report shows reported and scanned totals plus every classification.
- Museum IDs, original archive timestamps, and user Notes are immutable.
- Preserved artifacts are not deleted merely because Spotify no longer returns them.
- Duplicate Spotify track IDs cannot produce duplicate collection rows.
- An invalid or unexpectedly empty result cannot replace the saved collection.
- A no-change result is validated but does not rewrite `collection.csv`.

`Toolkit Version` records the toolkit version that first created an artifact. This
is creation provenance, not a “last updated by” field. Existing records therefore
retain `0.2`; artifacts first preserved by this release receive `0.3.1`.

## Optional popularity

`Popularity` is optional. The playlist endpoint used by the toolkit did not
populate it in the successful initial archive. The toolkit does not restrict the
playlist response with a field selection, and its converter already reads
`popularity` when Spotify supplies it. Missing or null values are stored as blank,
never cause an entry to be skipped, and never erase an existing nonblank value.

## Preserved metadata

The unchanged CSV schema contains title, artist, album, release date, duration,
optional popularity, Spotify URL, source identity, Museum ID, original archive
timestamp, creation-version provenance, status, and user Notes.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Roadmap

Lifecycle tracking, removal/restoration handling, saved reports, Obsidian
generation, artist/album pages, and statistics remain future work. They are
intentionally outside v0.3.1.
