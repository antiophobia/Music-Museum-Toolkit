"""
Music Museum Toolkit
Spotify API Tools
Version 0.3.1
"""

import os
import sys
import time

import spotipy
import requests
from requests.adapters import HTTPAdapter
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth
from urllib3.util.retry import Retry

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Config.config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI


MAX_AUTOMATIC_WAIT_SECONDS = 60
CLASSIFICATION_KEYS = (
    "valid_tracks",
    "duplicate_tracks",
    "local_files",
    "unavailable_entries",
    "unsupported_entries",
    "malformed_entries",
)


class SpotifyRateLimit(Exception):
    """Raised when Spotify asks the toolkit to stop and resume later."""

    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__(f"Spotify requested a {retry_after}-second cooldown")


def connect_spotify():
    print("Connecting to Spotify...")

    # Give Spotipy a session whose transport returns 429 responses directly.
    # Otherwise urllib3 converts the response into "Max Retries reached" and
    # discards the real Retry-After header before our safety logic can read it.
    session = requests.Session()
    no_transport_retries = Retry(
        total=0,
        connect=0,
        read=0,
        redirect=0,
        status=0,
        respect_retry_after_header=False,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=no_transport_retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope="playlist-read-private playlist-read-collaborative",
            cache_path=os.path.join(os.path.dirname(__file__), "..", ".cache"),
        ),
        requests_session=session,
        retries=0,
        status_retries=0,
    )

    profile = sp.current_user()
    name = profile.get("display_name", profile.get("id", "Unknown"))
    print(f"Spotify connection successful! Signed in as {name}.")
    return sp


def _retry_after_seconds(error):
    headers = error.headers or {}
    value = headers.get("Retry-After", headers.get("retry-after", 5))
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 5


def _artifact_from_track(track, requested_id):
    album = track.get("album") or {}
    popularity = track.get("popularity")
    return {
        "Spotify ID": track.get("id", requested_id),
        "Title": track.get("name", ""),
        "Artist": ", ".join(
            artist.get("name", "") for artist in track.get("artists", [])
        ),
        "Album": album.get("name", ""),
        "Release Date": album.get("release_date", ""),
        "Duration (ms)": track.get("duration_ms", ""),
        "Popularity": "" if popularity is None else popularity,
        "Spotify URL": (track.get("external_urls") or {}).get("spotify", ""),
    }


def classify_playlist_entries(entries, seen_track_ids=None):
    """Classify every playlist entry and return unique Spotify artifacts."""
    seen_track_ids = seen_track_ids if seen_track_ids is not None else set()
    counts = {key: 0 for key in CLASSIFICATION_KEYS}
    artifacts = []

    for entry in entries:
        if not isinstance(entry, dict):
            counts["malformed_entries"] += 1
            continue
        if "item" not in entry and "track" not in entry:
            counts["malformed_entries"] += 1
            continue

        track = entry.get("item") or entry.get("track")
        if track is None:
            counts["unavailable_entries"] += 1
            continue
        if not isinstance(track, dict):
            counts["malformed_entries"] += 1
            continue
        if track.get("is_local"):
            counts["local_files"] += 1
            continue
        if track.get("type") != "track":
            counts["unsupported_entries"] += 1
            continue

        track_id = track.get("id")
        if not isinstance(track_id, str) or not track_id.strip():
            counts["malformed_entries"] += 1
            continue
        if track_id in seen_track_ids:
            counts["duplicate_tracks"] += 1
            continue

        seen_track_ids.add(track_id)
        counts["valid_tracks"] += 1
        artifacts.append(_artifact_from_track(track, track_id))

    return artifacts, counts


def get_track_metadata(sp, track_id):
    """Fetch one track, briefly retrying only short Spotify cooldowns."""
    if not track_id:
        return None

    for attempt in range(2):
        try:
            track = sp.track(track_id)
            return _artifact_from_track(track, track_id) if track else None
        except SpotifyException as error:
            if error.http_status != 429:
                print(f"\nCould not archive {track_id}: {error}")
                return None

            retry_after = _retry_after_seconds(error)
            if retry_after > MAX_AUTOMATIC_WAIT_SECONDS or attempt == 1:
                raise SpotifyRateLimit(retry_after) from error

            print(f"\nShort rate limit. Waiting {retry_after} seconds once...")
            time.sleep(retry_after)

    return None


def _spotify_call(call):
    """Run an API call while preserving Spotify's real cooldown response."""
    for attempt in range(2):
        try:
            return call()
        except SpotifyException as error:
            if error.http_status != 429:
                raise
            retry_after = _retry_after_seconds(error)
            if retry_after > MAX_AUTOMATIC_WAIT_SECONDS or attempt == 1:
                raise SpotifyRateLimit(retry_after) from error
            print(f"\nShort rate limit. Waiting {retry_after} seconds once...")
            time.sleep(retry_after)
    return None


def get_playlist_summary(sp, playlist_id):
    """Return the playlist version marker and current live item count."""
    result = _spotify_call(
        lambda: sp.playlist(
            playlist_id,
            fields="name,snapshot_id,items.total",
        )
    )
    items = result.get("items") or result.get("tracks") or {}
    return {
        "name": result.get("name", "Spotify playlist"),
        "snapshot_id": result.get("snapshot_id", ""),
        "total": items.get("total", 0),
    }


def get_playlist_page(sp, playlist_id, offset, limit=50, seen_track_ids=None):
    """Fetch and classify one page, accounting for every returned entry."""
    result = _spotify_call(
        lambda: sp.playlist_items(
            playlist_id,
            limit=limit,
            offset=offset,
            additional_types=("track", "episode"),
        )
    )
    entries = result.get("items", [])
    if not isinstance(entries, list):
        entries = []
        counts = {key: 0 for key in CLASSIFICATION_KEYS}
        counts["malformed_entries"] = 1
        return [], result.get("next"), counts, 1
    artifacts, counts = classify_playlist_entries(entries, seen_track_ids)
    return artifacts, result.get("next"), counts, len(entries)


def get_tracks_metadata(sp, track_ids):
    """Compatibility wrapper for callers that still supply a list of IDs."""
    archived_tracks = []
    for track_id in track_ids:
        artifact = get_track_metadata(sp, track_id)
        if artifact:
            archived_tracks.append(artifact)
    return archived_tracks


if __name__ == "__main__":
    connect_spotify()
    print("Spotify API ready.")
