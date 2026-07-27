# Music Museum Toolkit Roadmap

## Delivered

### v0.4.0 — Playlist Restoration — 2026-07-26

- Guided reconstruction of the latest completed manifest into a new Spotify
  playlist.
- Exact stored-URI order with duplicate occurrence preservation.
- Private or public destination selection with separate scoped authorization.
- Atomic state and per-occurrence reports, safe resume, duplicate-aware remote
  reconciliation, stable destination reads, and visibility-before-add
  enforcement.
- Controlled live validation of 1,274 restored occurrences from a 1,282-row
  manifest, including all 3 duplicate placements and transparent reporting of 8
  exclusions.

## Future work

- Opt-in assisted matching for unavailable identities, kept separate from strict
  deterministic restoration.
- Apple Music and other service import/export adapters.
- Local-file discovery and user-guided handling.
- Historical manifest snapshot selection.
- Collection, manifest, and restoration validation UI.
- Additional archive formats, album artwork preservation, and extended metadata.
