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


def connect_spotify_restoration(public=False):
    """Authenticate restoration separately with only the required write scope."""
    print("Connecting to Spotify for playlist restoration...")
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

    write_scope = (
        "playlist-modify-public" if public else "playlist-modify-private"
    )
    scope = (
        "playlist-read-private playlist-read-collaborative " + write_scope
    )
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=scope,
            cache_path=os.path.join(
                os.path.dirname(__file__), "..", ".cache-restoration"
            ),
        ),
        requests_session=session,
        retries=0,
        status_retries=0,
    )
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


def classify_playlist_occurrences(
    entries,
    start_position,
    playlist_id,
    playlist_name,
    snapshot_id,
    captured_at,
    first_positions=None,
):
    """Classify entries while preserving one ordered row per occurrence."""
    first_positions = first_positions if first_positions is not None else {}
    counts = {key: 0 for key in CLASSIFICATION_KEYS}
    artifacts = []
    rows = []

    for index, entry in enumerate(entries):
        position = start_position + index
        row = {
            "Manifest Version": "1",
            "Playlist ID": playlist_id,
            "Playlist Name": playlist_name,
            "Snapshot ID": snapshot_id,
            "Captured At": captured_at,
            "Playlist Position": position,
            "Classification": "",
            "Restorable": "False",
            "Museum ID": "",
            "Source Track ID": "",
            "Spotify URI": "",
            "Title": "",
            "Artist": "",
            "Album": "",
            "Added At": entry.get("added_at", "") if isinstance(entry, dict) else "",
            "Duplicate Of Position": "",
            "Reason": "",
        }

        if not isinstance(entry, dict):
            row["Classification"] = "malformed entry"
            row["Reason"] = "Playlist entry is not an object."
            counts["malformed_entries"] += 1
            rows.append(row)
            continue
        if "item" not in entry and "track" not in entry:
            row["Classification"] = "malformed entry"
            row["Reason"] = "Playlist entry has no item or track field."
            counts["malformed_entries"] += 1
            rows.append(row)
            continue

        item = entry.get("item") if "item" in entry else entry.get("track")
        if item is None:
            row["Classification"] = "unavailable entry"
            row["Reason"] = "Spotify returned no item metadata for this occurrence."
            counts["unavailable_entries"] += 1
            rows.append(row)
            continue
        if not isinstance(item, dict):
            row["Classification"] = "malformed entry"
            row["Reason"] = "Playlist item metadata is not an object."
            counts["malformed_entries"] += 1
            rows.append(row)
            continue

        album = item.get("album") if isinstance(item.get("album"), dict) else {}
        show = item.get("show") if isinstance(item.get("show"), dict) else {}
        artists = item.get("artists") if isinstance(item.get("artists"), list) else []
        row.update({
            "Spotify URI": item.get("uri", "") or "",
            "Title": item.get("name", "") or "",
            "Artist": ", ".join(
                artist.get("name", "")
                for artist in artists
                if isinstance(artist, dict) and artist.get("name")
            ) or show.get("name", ""),
            "Album": album.get("name", "") or "",
        })

        if item.get("is_local"):
            row["Classification"] = "local file"
            row["Reason"] = "Local files cannot be restored through Spotify Web API."
            counts["local_files"] += 1
            rows.append(row)
            continue
        if item.get("type") != "track":
            row["Classification"] = "unsupported entry"
            row["Reason"] = (
                f"Spotify item type {item.get('type')!r} is not a supported track."
            )
            counts["unsupported_entries"] += 1
            rows.append(row)
            continue

        track_id = item.get("id")
        if not isinstance(track_id, str) or not track_id.strip():
            row["Classification"] = "malformed entry"
            row["Reason"] = "Spotify track has no usable source ID."
            counts["malformed_entries"] += 1
            rows.append(row)
            continue

        row["Source Track ID"] = track_id
        row["Restorable"] = "True"
        if track_id in first_positions:
            row["Classification"] = "duplicate occurrence"
            row["Duplicate Of Position"] = first_positions[track_id]
            counts["duplicate_tracks"] += 1
        else:
            row["Classification"] = "valid track"
            first_positions[track_id] = position
            counts["valid_tracks"] += 1
            artifacts.append(_artifact_from_track(item, track_id))
        rows.append(row)

    return artifacts, counts, rows


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
            fields="id,name,snapshot_id,items.total",
        )
    )
    items = result.get("items") or result.get("tracks") or {}
    return {
        "playlist_id": result.get("id", playlist_id),
        "name": result.get("name", "Spotify playlist"),
        "snapshot_id": result.get("snapshot_id", ""),
        "total": items.get("total", 0),
    }


def create_restoration_playlist(sp, name, public, description):
    """Create a new playlist through Spotify's current /me/playlists endpoint."""
    return _spotify_call(
        lambda: sp.current_user_playlist_create(
            name,
            public=bool(public),
            collaborative=False,
            description=description,
        )
    )


def change_restoration_playlist_visibility(sp, playlist_id, expected_public):
    """Explicitly enforce the confirmed destination visibility."""
    if not isinstance(expected_public, bool):
        raise ValueError("Expected playlist visibility must be a boolean.")
    return _spotify_call(
        lambda: sp.playlist_change_details(
            playlist_id,
            public=bool(expected_public),
            collaborative=False,
        )
    )


def add_restoration_items(sp, playlist_id, uris, position):
    if not uris or len(uris) > 100:
        raise ValueError("Spotify add batches must contain between 1 and 100 items.")
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ValueError("Spotify add position must be a nonnegative whole number.")
    return _spotify_call(
        lambda: sp.playlist_add_items(
            playlist_id,
            list(uris),
            position=position,
        )
    )


def _destination_identity(sp, playlist_id):
    details = _spotify_call(
        lambda: sp.playlist(
            playlist_id,
            fields=(
                "id,name,owner.id,public,collaborative,description,snapshot_id,"
                "external_urls,items.total"
            ),
        )
    )
    items = details.get("items") or details.get("tracks") or {}
    total = items.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError("Spotify returned an invalid destination item total.")
    public = details.get("public")
    if (
        not (public is None or isinstance(public, bool))
        or not isinstance(details.get("collaborative"), bool)
    ):
        raise ValueError(
            "Spotify returned invalid destination visibility or collaboration data."
        )
    identity = {
        "playlist_id": details.get("id", ""),
        "name": details.get("name", ""),
        "owner_id": (details.get("owner") or {}).get("id", ""),
        "public": public,
        "collaborative": details["collaborative"],
        "description": details.get("description", ""),
        "snapshot_id": details.get("snapshot_id", ""),
        "url": (details.get("external_urls") or {}).get("spotify", ""),
        "reported_total": total,
    }
    if not identity["playlist_id"] or not identity["snapshot_id"]:
        raise ValueError(
            "Spotify returned incomplete destination identity or snapshot data."
        )
    return identity


def get_destination_playlist(sp, playlist_id):
    """Return one snapshot-stable destination identity and URI sequence."""
    before = _destination_identity(sp, playlist_id)
    uris = []
    offset = 0
    while True:
        page = _spotify_call(
            lambda offset=offset: sp.playlist_items(
                playlist_id,
                limit=50,
                offset=offset,
                additional_types=("track", "episode"),
            )
        )
        items = page.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Spotify returned malformed destination playlist items.")
        for entry in items:
            if not isinstance(entry, dict):
                uris.append("")
                continue
            item = entry.get("item") if "item" in entry else entry.get("track")
            uris.append(
                item.get("uri", "") if isinstance(item, dict) else ""
            )
        if not page.get("next"):
            break
        offset += len(items)
        if not items:
            raise ValueError("Spotify destination pagination did not advance.")
    after = _destination_identity(sp, playlist_id)
    stable_fields = (
        "playlist_id",
        "owner_id",
        "name",
        "public",
        "collaborative",
        "description",
        "snapshot_id",
        "reported_total",
    )
    if any(before[field] != after[field] for field in stable_fields):
        raise ValueError(
            "Destination playlist changed while its items were being read."
        )
    if before["playlist_id"] != playlist_id:
        raise ValueError("Spotify returned a different destination playlist ID.")
    if len(uris) != before["reported_total"]:
        raise ValueError(
            "Destination item rows do not match Spotify's stable reported total."
        )
    result = dict(after)
    result["uris"] = uris
    return result


def find_restoration_playlists(sp, run_id):
    """Find current-user playlists carrying an exact restoration run marker."""
    marker = f"Restoration run: {run_id}"
    matches = []
    offset = 0
    while True:
        page = _spotify_call(
            lambda offset=offset: sp.current_user_playlists(
                limit=50, offset=offset
            )
        )
        items = page.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Spotify returned malformed current-user playlists.")
        matches.extend(
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("description", "")).rstrip().endswith(marker)
        )
        if not page.get("next"):
            return matches
        offset += len(items)
        if not items:
            raise ValueError("Spotify playlist discovery pagination did not advance.")


def get_current_user_identity(sp):
    profile = _spotify_call(lambda: sp.current_user())
    return {
        "id": profile.get("id", ""),
        "name": profile.get("display_name", profile.get("id", "Unknown")),
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


def get_playlist_page_occurrences(
    sp,
    playlist_id,
    offset,
    limit,
    start_position,
    playlist_name,
    snapshot_id,
    captured_at,
    first_positions,
):
    """Fetch one page and return artifacts, counts, and ordered manifest rows."""
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
        entries = [entries]
    artifacts, counts, rows = classify_playlist_occurrences(
        entries,
        start_position,
        playlist_id,
        playlist_name,
        snapshot_id,
        captured_at,
        first_positions,
    )
    return artifacts, result.get("next"), counts, len(entries), rows


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
