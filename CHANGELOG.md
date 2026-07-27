# Changelog

## Unreleased

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
