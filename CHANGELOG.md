# Changelog

## Unreleased

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
- Added the first user-facing application menu with preserve, restore-placeholder,
  and exit options.
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
