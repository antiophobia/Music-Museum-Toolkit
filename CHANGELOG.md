# Changelog

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
