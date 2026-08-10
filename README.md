# 🎵 Music Museum Toolkit

> **Transform Spotify playlists into a permanent, versioned music archive.**

<p align="center">
  <img src="assets/demo.gif" width="900" alt="Music Museum Toolkit Demo">
</p>

Music Museum Toolkit is an open-source digital preservation toolkit that
preserves Spotify playlists as structured, long-term personal archives and can
reconstruct them later as new Spotify playlists.

```text
Spotify playlist
    -> permanent Collection and occurrence manifest
    -> reconstructed Spotify playlist
```

The preserved record is more than song metadata. It retains stable artifact
identity, playlist identity, exact occurrence order, duplicate placement, and an
accountable record of every local, unavailable, unsupported, or malformed entry
that Spotify cannot restore.

---

# ✨ Features

- 🎵 Live Spotify playlist preservation through the official Web API
- 🏛️ Stable Museum IDs for every permanently preserved track
- 📚 Permanent unique-artifact Collection with rich metadata
- 📋 Occurrence-level playlist manifest
- 🔢 Exact playlist order and duplicate occurrence preservation
- 🔍 Classification of local, unavailable, unsupported, and malformed entries
- ↩️ Guided playlist restoration into a new Spotify playlist
- 🔒 Private or public destination choice
- 🔑 Separate, narrowly scoped restoration authorization
- 🎯 Exact deterministic Spotify URI restoration with no fuzzy matching
- 📦 Ordered add batches of no more than 100 items
- 💾 Atomic local restoration state and per-occurrence reports
- 🔄 Safe interruption, checkpointing, and resume
- ✅ Duplicate-aware remote reconciliation and exact final verification
- 👁️ Explicit destination visibility enforcement and verification
- 📄 Permanent restoration report, including every excluded occurrence
- 🧪 Regression-tested preservation and restoration behavior
- 🔓 Fully open source

---

# Why?

Streaming services are designed for **access**, not **preservation**.

Songs disappear.

Albums change.

Metadata evolves.

Playlists are edited.

Platforms come and go.

Music Museum Toolkit exists to preserve your music collection independently of the service that originally hosted it.

Instead of asking:

> *"Can I export my playlist?"*

the project asks:

> **"How can I preserve this collection for years to come?"**

---

# Current Capabilities

Current Version: **v0.4.0 — Playlist Restoration**

The toolkit now completes both directions of the preservation loop:

- preserve a live Spotify playlist into permanent, locally owned Collection and
  manifest records;
- resume interrupted preservation without weakening stable Museum IDs or
  rewriting unchanged data;
- reconstruct the latest completed manifest into a new private or public Spotify
  playlist;
- preserve duplicate occurrences and exact restorable order;
- report every occurrence that cannot be restored and the reason;
- safely resume a partially completed restoration after reconciling the remote
  playlist against the deterministic plan.

## First run on Windows

No command prompt is required for normal use:

1. Extract or clone Music Museum Toolkit.
2. Double-click **Music Museum Toolkit.bat**.
3. Choose **Museum**.
4. If prompted, put your untouched Spotify ZIPs in `Input/Spotify Data/`.
5. Choose **Import Museum Data**, review the preview, and confirm.
6. Search, inspect, and browse your Museum.

On every startup, the Toolkit safely creates missing `Input/`,
`Input/Spotify Data/`, `Output/`, and `Logs/` directories. Existing folders and
files are never erased or replaced by startup initialization. The launcher moves
to its own repository directory before starting Python, so double-clicking works
regardless of Windows' current working directory.

The credential-free application menu is:

```text
Music Museum Toolkit
v0.4.0 + Museum development build

[1] Preserve Spotify playlist to Collection
[2] Restore Spotify playlist from Collection
[3] Museum
[4] Exit
```

Museum import and browsing are entirely local and do not require Spotify API
credentials. Preserve and Restore connect directly to Spotify and require a
Spotify Developer client ID and client secret. Those modules are loaded only when
their menu options are selected. If configuration is missing, the Toolkit shows
setup help and returns to the menu—there is no startup traceback and no fake
credential file is created.

For Preserve or Restore, copy `.env.example` to `.env`, add your Spotify
Developer values, and keep that file private. The Toolkit never prints those
values. This setup is optional for Museum-only use.

Option 3 opens the experimental Museum prototype. The normal import workflow is:

1. Download your Spotify data archive.
2. Put each untouched `.zip` file in `Input/Spotify Data/`.
3. Double-click **Music Museum Toolkit.bat**.
4. Choose **Museum**.
5. Choose **Import Museum Data**.
6. Confirm the detected ZIP scan, review the scan-only counts, and confirm the
   permanent import.
7. Search or inspect artifacts and browse exhibits.

The ZIPs are opened read-only. Supported JSON members are decoded in memory and
are never permanently extracted into the repository. The scanner recognizes data
from record structure rather than ZIP filenames, rejects unsafe member paths, and
never overwrites the original archive. A direct JSON file or previously extracted
folder remains supported through the manual-path prompt.

The scan-only preview reports recognized files, playback records, exact-URI and
title/artist-only records, already-imported events, unresolved and ambiguous
identity, malformed records, and ignored technical telemetry. No Listening Archive
write occurs until the user confirms the preview. Both simple
`endTime`/artist/title history and richer URI/playback-context records are
supported through a source adapter.

Large supported members are processed in deterministic batches of 1,000 records
by default. The terminal reports the active archive/member, batch number, records
processed, playback records found, and identity counts. Collection identity
indexes are built once per scan, so batch progress does not repeat a full
Collection walk for every playback event. Batch size does not affect Event IDs or
normalized output.

On an empty first run, Museum Home explains where to place ZIPs and directs the
user to option 7. If no ZIP is present, Import Museum Data gives the same short
relative path and returns safely; an advanced direct-file/folder prompt remains
available. Unexpected internal failures are recorded as stack-only, redacted
diagnostics under `Logs/`, while expected missing-data, malformed-input, and menu
errors stay as concise terminal messages.

The Museum can search preserved artifacts by song, artist, album, combined terms,
Spotify URI, or Museum ID. It derives Artifact, Artist, Album, and Listening
Overview statistics from the private local Listening Archive. Artifact inspection
shows available preserved identity, duration and preservation metadata; playback
counts; time and completion aggregates; year/month/hour activity; reasons;
shuffle/offline state; device, OS and country context; and playlist occurrence
history. Unsupported values are omitted rather than displayed as invented zeroes.
Search may offer a conservative fuzzy selection, but fuzzy results never change
permanent identity.

The Automatic Exhibit Engine turns the Museum into a browse-first experience.
Museum Home highlights supported featured exhibits, and Browse Exhibits groups
saved views into Featured, Listening, Artists, Albums, Time, Behavior, Devices &
Context, Preservation, Generated, and Curated sections. The supported catalog is
created from the data actually available and includes listening leaders, recorded
relationships, completion and explicit-skip evidence, time-of-day and calendar
views, device/offline/shuffle context, playlist mainstays, repeated occurrences,
and preserved release/duration views. An exhibit can be opened by display number
or title, and ranked results link directly to Artifact, Artist, Album, year, or
month context.

Automatic exhibits are saved definitions, not snapshots: `exhibits.json` never
contains copied listening-event payloads or derived result rows. Results refresh
from the current Collection, Listening Archive, and manifest whenever a Museum
browse session builds its shared aggregate index. Each view states its basis,
coverage, and a short factual story. Skip/completion rates require at least five
recorded events, unknown fields are not invented, unresolved or ambiguous events
do not enter artifact rankings, and timestamp bucketing uses stored timestamp
hours (UTC when the source timestamp is UTC). Preserved multi-artist credits are
treated as one credit string; the engine does not infer individual collaborators.

Generated Artist/Album views remain derived on demand. Curated exhibits remain
separate user-owned lists with explicit add/remove membership and reorderable
display order; catalog refresh never rewrites them.

Museum data is deliberately separate from `collection.csv`:

- `Output/listening_archive.jsonl` stores validated, normalized,
  provenance-bearing playback events in deterministic timestamp/Event-ID order;
- `Output/exhibits.json` stores validated exhibit definitions and dependency
  declarations;
- Collection identity is linked by exact Spotify URI when available, or by one
  unique exact normalized title+artist match when no URI was exported;
- unresolved events remain unresolved and never mutate artifact identity.

Playback labels are centralized: a recorded event is any normalized event;
meaningful plays reach 30 seconds; completed plays use explicit completion or a
documented 90% duration fallback; explicit skips require explicit evidence;
short plays are not automatically skips; other interruptions remain distinct.

The archive currently imports downloaded history as
`historical_authoritative`. Its schema also reserves `provisional` and
`reconciled` authority states for a future update pipeline. Live listening sync
is intentionally not implemented in this release-in-progress.

## Preservation outputs

`Output/collection.csv` is the permanent source of truth for unique artifacts,
stable Museum IDs, and preserved metadata.

`Output/playlist_manifest.csv` is the source of truth for the most recently
completed playlist snapshot's occurrence order. It contains one row for every
returned playlist entry, including duplicate placements, local files, unavailable
items, unsupported items such as episodes, and malformed entries. Valid and
duplicate Spotify tracks map back to the same permanent Museum ID.

Interrupted scans checkpoint manifest rows in
`Output/playlist_manifest.checkpoint.csv`. The permanent manifest is validated and
replaced atomically only after a complete scan. The manifest supplies the exact
order for restoration.

## Playlist restoration

Restoration validates `collection.csv`, `playlist_manifest.csv`, and
`playlist_sync.json` before Spotify authorization. It uses only stored Spotify
track identities and preserves duplicate occurrences in their original order.

Restoration v1 follows a deliberately strict policy:

- stored Spotify track identities only;
- no fuzzy title/artist matching and no silent substitutions;
- local files, unavailable entries, episodes or other unsupported entries, and
  malformed entries are not added;
- every excluded occurrence remains in the permanent report with its reason;
- restoration always creates a new playlist and never edits the source playlist;
- a recoverable run reuses its existing run-bound destination instead of creating
  another playlist.

Local files, unavailable entries, unsupported entries, and malformed entries are
not added, but every occurrence is retained in the restoration report with its
reason. The verified manifest produces 1,274 planned items, 8 not-included rows,
and 13 add batches of at most 100 items.

Preservation remains read-only. Restoration requests its separate write
authorization only after explicit creation confirmation or when resuming a
recoverable run. Private restoration requests only `playlist-modify-private`;
public restoration requests only `playlist-modify-public`, alongside the existing
read scopes. A separate `.cache-restoration` OAuth cache keeps preservation
authorization isolated.

Spotify creation uses Spotipy's `current_user_playlist_create()`, which targets
the current `POST /me/playlists` endpoint. Spotipy 2.26.0 was verified locally.
Items are added with `playlist_add_items()` and reconciled with
`playlist_items()`.

Restoration progress is stored atomically in
`Output/restoration_state.json`. Reports are stored under
`Output/Restoration Reports/`. State and the complete occurrence report are
validated together before restoration authorization. Before every resume, the
remote URI sequence must be an exact prefix of the saved plan; final success
requires a complete exact sequence match. Partial playlists are retained for safe
resume and are never deleted automatically.

Successful add batches use an explicit destination position and Spotify's returned
snapshot ID as their checkpoint, without rereading the growing playlist after
every batch. A full destination read is reserved for initial/resume
reconciliation, ambiguous or unconfirmed add outcomes, and final verification.
Each full read checks playlist identity, ownership, name, visibility,
collaborative state, snapshot ID, and reported total both before and after paging,
and rejects any mixed or incomplete read.

A private live test exposed a Spotify discrepancy: creation returned the requested
private visibility, but the following stable read reported the new playlist as
public. The toolkit therefore explicitly enforces the confirmed visibility with
`playlist_change_details()` before restoration begins. It first requires the
destination ID, owner, name, noncollaborative state, and exact run-ID marker to
match the saved restoration. After any visibility change, bounded stable reads
must conclusively return the requested boolean value. `public=null` is not treated
as private, and no playlist items are submitted until visibility is verified.

If playlist creation has an uncertain outcome, the run-ID marker is searched
without automatically issuing a second create request. A later run searches
again; if no match is visible, the user must separately confirm that the Spotify
account was checked before retrying creation.

---

# Live Validation

The first controlled live reconstruction completed successfully on July 26,
2026:

- 1,282 source manifest occurrences;
- 1,274 ordered occurrences restored in 13 batches;
- 1,271 unique Spotify tracks plus all 3 duplicate placements;
- 8 transparently reported nonrestorable occurrences: 3 local files, 3
  unavailable entries, 2 unsupported entries, and 0 malformed entries;
- 0 failed and 0 pending report rows;
- exact contiguous source and destination positions, stored URI identity, Museum
  ID mapping, and final destination length verified.

The initial private-playlist attempt exposed a Spotify visibility discrepancy.
The toolkit stopped before adding any tracks. The hardened resume reused that
same run-bound playlist, verified private visibility, restored all 1,274 planned
occurrences, and completed exact final reconciliation.

No private playlist URL, account identity, run marker, or Spotify snapshot
identifier is published here.

## Setup and local-data safety

- Keep Spotify credentials in `.env`; never commit that file.
- Never commit OAuth caches, including `.cache` and `.cache-restoration`.
- Never commit personal `Input/`, `Output/`, or `Logs/` data, restoration reports,
  or `restoration_state.json`.
- The supplied `.gitignore` excludes these local files by default.

---

# Example Output

Each preserved song becomes a permanent artifact.

| Museum ID | Title | Artist | Album |
|-----------|--------|--------|-------|
| MMT-000001 | ... | ... | ... |
| MMT-000002 | ... | ... | ... |

Every artifact also stores:

- Source Track ID
- Release Date
- Duration
- Popularity
- Spotify URL
- Archived Timestamp
- Toolkit Version
- Preservation Status

---

# Philosophy

Music Museum Toolkit is intentionally built around digital preservation principles.

The goal is not simply to download information from Spotify.

The goal is to create a personal music archive that can continue to exist regardless of future platform changes.

Every design decision follows that philosophy.

---

# Roadmap

Planned future work includes:

- Additional archive formats
- Album artwork preservation
- Extended metadata support
- Opt-in assisted matching without weakening strict restoration defaults
- Apple Music and other service integrations
- Local-file handling
- Collection and validation UI improvements

Playlist restoration v1 is delivered in v0.4.0. See **ROADMAP.md** for longer-term
work.

---

# Contributing

Suggestions, issues, and pull requests are always welcome.

Whether you're interested in software engineering, digital preservation, metadata, or simply preserving your own music collection, contributions are appreciated.

---

# License

This project is open source.

Build your own museum.

Preserve your music.
