# Changelog

## Unreleased

- Added the Automatic Exhibit Engine: schema-v2 saved-view definitions,
  deterministic/idempotent catalog IDs, safe schema-v1 migration, supported-data
  initialization, and a shared Collection/Listening Archive/manifest aggregate
  index. Automatic exhibits persist no copied events or derived result rows.
- Added a substantial exhibit catalog across Featured, Listening, Artists,
  Albums, Time, Behavior, Devices & Context, and Preservation, including annual
  and monthly views, recorded relationships/gaps, completion and explicit-skip
  evidence, device/offline/shuffle context, playlist occurrences, and preserved
  release/duration views. Central coverage and five-event rate thresholds avoid
  invented certainty.
- Redesigned Museum Home and Browse Exhibits around featured/category discovery,
  factual quick stories, coverage statements, title/number selection, and direct
  navigation to Artifact, Artist, Album, year, and month context. Generated and
  curated ownership remains separate; catalog refresh never overwrites curated
  membership.

- Made application startup credential-free through lazy Preserve/Restore/Museum
  imports and delayed Spotify configuration validation. Museum now opens fully
  offline; selecting an API feature without credentials shows setup help and
  returns to the root menu.
- Added idempotent first-run creation of `Input/`, `Input/Spotify Data/`,
  `Output/`, and `Logs/`, a visible development-build version label, a portable
  BAT/Python check, and privacy-conscious stack-only runtime error logging.
- Added empty-Museum and no-ZIP guidance using short relocatable paths while
  retaining the advanced direct-file/folder import option.
- Hardened private restoration for Spotify's nullable visibility response with a
  distinct `private_requested_api_ambiguous` state after exact run-bound identity,
  local bundle validation, an explicit private-setting request, and bounded reads.
  Explicit `public=true` contradictions—including contradictions during bounded
  rereads—stop before item submission and are never corrected silently.
- Added deterministic deleted-destination handling: conclusive 404 only,
  historical abandoned-state evidence beside the untouched prior report, explicit
  replacement confirmation, and fresh run/report/destination identity. A second,
  destination-specific 404 is required; transient or operation-level ambiguity is
  not treated as deletion.
- Added the experimental Listening Archive, exact URI mapping, centralized playback
  classifications, artifact search/inspection, exhibit identity/persistence and
  automatic recalculation, plus the Museum application submenu.
- Added scan-before-import support for simple and rich Spotify playback JSON,
  conservative exact title+artist fallback, explicit ambiguous/unresolved records,
  portable authority provenance, and technical-telemetry exclusion.
- Added automatic discovery of untouched ZIPs under `Input/Spotify Data/`,
  in-memory JSON-member scanning, traversal/size/count safeguards, basename-only
  provenance, and continued direct-JSON/extracted-folder support.
- Added visible archive/member/batch scan progress; 1,000-record default Museum
  batches; one-time Collection/Event-ID indexes; schema-key classification
  caching; and field-based `RawCoreStream` playback recognition. Rich technical
  playback now preserves available URI, duration, reasons, shuffle, downloaded,
  device, OS, country, social-listening, and session context without admitting
  unrelated telemetry.
- Added derived Artifact, Artist, Album, time-pattern and listening-behavior
  inspection; ranked/fuzzy-selection search; automatic starter exhibits;
  generated artist results; curated exhibit creation and membership; exhibit
  reordering and dependency declarations.
- Expanded terminal inspection to show available URI/duration/preservation data,
  playlist occurrence history, year/month/hour activity, reasons, shuffle,
  offline, device, OS, and country context without fabricating missing durations.
- Added synthetic offline regression coverage; no personal Spotify exports or
  technical logs are stored in the repository. The 162-test suite runs with no
  `.env` and no credential placeholders, including root/Museum startup, setup
  guidance, folder preservation, BAT portability, and redacted logging.

## v0.4.0 — Playlist Restoration — 2026-07-26

- Released restoration v1 with a guided menu workflow that rebuilds the latest
  completed occurrence manifest into a newly created private or public Spotify
  playlist.
- Restored exact stored Spotify URI order, including duplicate placements, in
  positioned batches of no more than 100; no fuzzy matching, substitution, or
  silent omission is permitted.
- Added an atomic write-side state file and permanent per-occurrence CSV report,
  with exact-prefix resume, duplicate-aware reconciliation, uncertain-write
  recovery, and final whole-sequence verification.
- Kept preservation read-only and isolated restoration authorization in a
  separate cache with only the write scope required by the selected visibility.
- Made full destination reads snapshot-stable and limited them to initial/resume
  reconciliation, ambiguous or unconfirmed writes, and exact final verification.
- Required immutable run-bound destination identity validation before mutation
  and conclusive visibility enforcement before any playlist items are submitted.
- The first controlled live attempt exposed Spotify reporting the new private
  playlist as public; the safety checks stopped before adding any tracks.
- The hardened resume reused that same recoverable playlist, verified private
  visibility, and completed all 1,274 additions across 13 batches.
- Live validation confirmed 1,282 source occurrences, 1,271 unique tracks, 3
  duplicate occurrences restored separately, and 8 reported exclusions (3 local,
  3 unavailable, 2 unsupported, 0 malformed), with no failed or pending rows.

- Hardened restoration after a private live test returned a private creation
  response but a subsequent stable Spotify read reported the playlist as public.
- Added explicit post-creation visibility enforcement through
  `playlist_change_details()` only after exact destination ID, owner, name,
  collaboration state, run marker, and local plan/report validation.
- Added bounded stable visibility verification; null or persistently incorrect
  visibility stops before any item add and preserves the existing recoverable
  playlist without another creation request.
- Reduced normal restoration traffic by checkpointing successful positioned add
  batches from their returned snapshot IDs instead of rereading the complete
  growing destination after every batch.
- Limited full remote reconciliation to initial/resume checks, ambiguous or
  unconfirmed add outcomes, and exact final verification.
- Made every full destination read snapshot-stable by comparing playlist identity,
  ownership, settings, snapshot ID, and reported total before and after pagination
  and reconciling returned rows to the stable total.
- Required separate user confirmation before retrying an uncertain playlist
  creation when no exact run-ID match is visible.
- Added pre-authorization validation for in-progress restoration state and the
  complete per-occurrence report, including path, schema, identity, placement,
  bounds, and result semantics.
- Added restoration v1 for the latest completed manifest. Restoration always
  creates a new playlist and never changes an existing playlist.
- Added exact stored-ID planning, duplicate preservation, nonrestorable occurrence
  reporting, 100-item batching, and full final sequence verification.
- Added atomic restoration state and per-occurrence reports with safe resume from
  an exact duplicate-aware remote prefix.
- Added unique run-ID creation recovery and conservative ambiguous-write
  reconciliation without automatic deletion.
- Added separate restoration OAuth caching and visibility-specific write scopes.
- Used Spotipy `current_user_playlist_create()` for `POST /me/playlists`,
  `playlist_add_items()` for batches, and `playlist_items()` for reconciliation.
- Added manifest version 1 with one ordered row per playlist occurrence, including
  duplicate, local, unavailable, unsupported, and malformed entries.
- Added permanent Museum ID mapping for valid and duplicate occurrences.
- Added manifest validation, atomic permanent saving, semantic unchanged
  detection, and per-page atomic checkpointing.
- Added a post-scan playlist summary check requiring playlist ID, name, snapshot
  ID, and reported total to remain stable before candidates are built or saved.
- Added a completeness gate requiring scanned entries, manifest rows, and the
  stable reported total to match, with classifications reconciling to scanned
  entries.
- Invalidated incomplete-scan checkpoints/state so the following run starts clean.
- Requested Spotify's returned playlist `id` explicitly during summary calls.
- Hardened resume validation for whole/unique/contiguous positions, full identity
  and capture consistency, allowed values, duplicate linkage, and saved-report
  reconciliation.
- Removed redundant `seen_track_ids` resume state; manifest first-occurrence
  positions are authoritative.
- Clarified that each permanent file replacement is atomic, while the collection
  and manifest saves together are a recoverable sequence rather than one
  filesystem transaction.
- Made completed-snapshot shortcuts require a valid matching permanent manifest;
  legacy completed snapshots perform one full read-only scan to establish it.
- Preserved the v0.3.1 collection schema, Toolkit Version provenance, validation,
  checkpointing, menu, direct entry point, and read-only Spotify scopes.
- Added the first user-facing application menu with preserve, restore, and exit
  options.
- Added a Windows launcher that runs from the repository root and pauses on
  unexpected Python failure.
- Kept `archive.main()` as the single preservation workflow for both menu and
  direct-script execution.
- Added offline menu tests for dispatch, return behavior, invalid input, and
  interruption handling.

## v0.3.1 — 2026-07-24

- Defined `Toolkit Version` as artifact-creation provenance and set new artifacts
  to `0.3.1` without rewriting historical `0.2` records.
- Added exhaustive playlist-entry classification and detailed resumable reporting.
- Added pre-save identity, uniqueness, nonempty-result, and preservation validation.
- Preserved Museum IDs, original archive timestamps, Notes, and nonblank optional
  metadata across reruns.
- Avoided permanent collection rewrites when the validated result is unchanged.
- Documented blank popularity as optional and safe.
- Added focused v0.3.1 regression tests.
- Corrected unchanged-save detection so integer API metadata and string CSV
  metadata compare semantically instead of triggering a dtype-only rewrite.
- Added explicit “validated and not rewritten” console reporting for full scans
  and completed-snapshot shortcuts.
- Added a classification-total integrity check before printing a completed report.
