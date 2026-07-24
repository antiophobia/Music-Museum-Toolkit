# Music Museum Toolkit Development Handoff

## Mission

Preserve a person's musical history in a permanent, locally owned collection that
does not depend on Spotify remaining available.

## Current version

v0.3.1 — Validation and hardening

## Verified starting state

The July 24, 2026 initial live sync reported 1,273 playlist items, scanned 26
pages, and preserved 1,262 artifacts. The saved CSV has 1,262 unique Museum IDs
from `MMT-000001` through `MMT-001262` and 1,262 unique Spotify source IDs.
Spreadsheet duplicate-looking IDs and `########` timestamps were display issues.

The first complete live v0.3.1 scan subsequently accounted for all entries:
1,262 valid unique tracks, 3 duplicate occurrences, 3 local files, 3 unavailable
entries, 2 unsupported entries, and 0 malformed entries. These total all 1,273
entries scanned. It added 0 artifacts and found 0 metadata updates.

## Implementation summary

- Defined `Toolkit Version` as creation provenance. Existing artifacts keep `0.2`;
  artifacts first created now receive `0.3.1`.
- Classified every returned playlist entry as valid unique track, duplicate
  occurrence, local file, unavailable/null, unsupported type, or malformed.
- Persisted counts and scan-seen IDs in resume state for whole-run accounting.
- Added a detailed final/unchanged-snapshot report.
- Added validation for schema, nonempty results, identity fields, Museum ID format
  and uniqueness, Spotify source-ID uniqueness, existing artifact retention, and
  immutable Museum ID/Archived At/Notes values.
- Kept the existing collection schema unchanged.
- Preserved nonblank optional metadata when a later payload is blank.
- Avoided rewriting an unchanged permanent collection.
- Normalized representation-only differences during save comparison, including
  numeric API values versus string CSV values, null/blanks, index, column order,
  and row order.
- Added an integrity check requiring classification categories to total the number
  of entries scanned.
- Retained atomic CSV/JSON writes and per-page checkpoint behavior.

## Files changed

- `Scripts/archive.py` — reporting, resumable counters, safe metadata merge,
  validation-before-save orchestration, v0.3.1 display.
- `Scripts/spotify_api.py` — exhaustive item classification, episode retrieval for
  accounting, safe blank popularity normalization, v0.3.1 provenance.
- `Scripts/collection_manager.py` — version semantics, integrity/preservation
  validator, unchanged-save detection.
- `tests/test_v031.py` — 15 focused regression tests.
- `README.md` — v0.3.1 usage and behavior.
- `ARCHITECTURE.md` — created with the complete sync and safety architecture.
- `CHANGELOG.md` — concise v0.3.1 entry.
- `DEV_HANDOFF.md` — this handoff.

No collection data, playlist input, credentials, or schema columns were changed.

## Tests and verification

Commands run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q Scripts tests
```

Result: 15 tests passed; compilation passed.

An offline integrity check loaded the real collection, validated it with zero
errors, confirmed 1,262 unique Museum IDs and source IDs, and confirmed that a
no-change rebuild is exactly equal to the saved DataFrame.

Covered cases:

- duplicate Museum ID rejection;
- duplicate Spotify source-ID rejection;
- invalid Museum ID format;
- preservation of Museum ID, Archived At, Notes, and creation version;
- unchanged-sync idempotency;
- exhaustive playlist classification;
- null/unavailable track safety;
- blank popularity acceptance and non-erasure;
- refusal to save an empty invalid result.
- semantic comparison of integer/string and DataFrame representation differences;
- unchanged-save console reporting and proof that the atomic writer is not called;
- proof that genuine metadata changes still call the atomic writer;
- complete classification-summary output and total checking.

## Unchanged-save investigation

The first full live v0.3.1 run did rewrite `collection.csv`. The console
`Collection saved:` line is emitted only after `_atomic_save` returns, so it was
not merely a reporting error.

The root cause was dtype-sensitive `DataFrame.equals()`. CSV values load as
strings, while Spotify supplies duration as integers. The merge correctly reported
those durations as logically unchanged using text normalization, but retained the
integer representation in the candidate. Pandas therefore considered the frames
unequal solely because their dtypes differed.

The save path now validates first, compares canonical semantic views, and prints:

```text
Collection unchanged:
C:\Users\Admin\OneDrive\Documents\Music Museum Toolkit\Output\collection.csv was validated and not rewritten.
```

The completed-snapshot shortcut uses this same validated no-write path.

## Popularity finding

The code does not limit playlist item fields and reads `popularity` when present.
The initial live payload nevertheless produced no popularity values. v0.3.1 treats
this field as optional: absent/null becomes blank, cannot skip a track, and cannot
erase an existing nonblank value. A separate per-track enrichment request was not
added because it would create substantial API traffic for optional metadata.

## Remaining concerns

- Spotify could change playlist payload shapes; unknown shapes will be counted as
  malformed rather than silently discarded.
- `Config/config.py` already contains credentials directly in source. This
  pre-existing secret-handling risk was not changed during the scoped v0.3.1 pass;
  rotate exposed credentials and move them to environment-based configuration in
  a separately reviewed security task.
- There is no repository metadata in this project directory, so no version-control
  diff or commit was produced.

## Recommended next task

No additional live Spotify scan is required for correctness. An optional
confirmation run should take the completed-snapshot shortcut, validate the saved
collection, report that it was not rewritten, and replay the stored complete
classification summary.

Command:

```powershell
python Scripts\archive.py
```

Do not begin v0.4 lifecycle or Obsidian/statistics/page generation until that live
validation is complete.
