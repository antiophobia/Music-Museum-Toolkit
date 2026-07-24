# 🎵 Music Museum Toolkit

> **Transform Spotify playlists into a permanent, versioned music archive.**

<p align="center">
  <img src="assets/demo.gif" width="900" alt="Music Museum Toolkit Demo">
</p>

Music Museum Toolkit is an open-source digital preservation toolkit that transforms Spotify playlists into a structured, long-term personal archive.

Rather than treating playlists as temporary collections, Music Museum Toolkit preserves them as permanent records with stable identities, metadata tracking, resumable synchronization, and version-aware preservation.

---

# ✨ Features

- 🎵 Connect directly to Spotify using the official Web API
- 🏛️ Permanent Museum IDs for every preserved track
- 📚 Rich metadata preservation
- 🔄 Resume interrupted archive sessions automatically
- ✅ Validation before rewriting existing collections
- 📄 Export preservation-ready CSV archives
- 🔍 Duplicate detection and playlist integrity checks
- 🧪 Regression-tested synchronization logic
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

Current Version: **v0.3.1**

The toolkit currently supports:

- Spotify authentication
- Playlist scanning
- Metadata retrieval
- Stable artifact identification
- Incremental synchronization
- Resume support after interrupted archive sessions
- Duplicate handling
- Metadata change detection
- Validation without unnecessary rewrites
- Preservation-oriented CSV generation

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
- New collection management features
- Additional music service integrations
- Improved preservation tooling

See **ROADMAP.md** for planned releases.

---

# Contributing

Suggestions, issues, and pull requests are always welcome.

Whether you're interested in software engineering, digital preservation, metadata, or simply preserving your own music collection, contributions are appreciated.

---

# License

This project is open source.

Build your own museum.

Preserve your music.