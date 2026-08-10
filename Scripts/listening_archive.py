"""Portable, private, provenance-preserving normalized listening archive.

JSON Lines keeps each event human-inspectable and streamable. Event identity is
the SHA-256 of stable source identity and musical/playback facts; import time and
row order are deliberately excluded. A hash collision with different content is
rejected rather than silently merged.
"""

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone


ARCHIVE_VERSION = "3"
DEFAULT_BATCH_SIZE = 1000
AUTHORITY_STATUSES = {"historical_authoritative", "provisional", "reconciled"}
MATCH_STATUSES = {"exact_uri", "exact_title_artist", "unresolved", "ambiguous"}
MATCH_METHODS = {"spotify_uri", "normalized_title_artist", "none"}
INTERRUPTION_END_REASONS = {
    "app load", "connection error", "error", "logout", "playback error",
    "remote", "remote action", "remote transfer", "transfer",
}
EVENT_FIELDS = (
    "event_id", "archive_version", "source_type", "source_file",
    "source_record_id", "source_schema_version", "imported_at",
    "event_timestamp", "end_timestamp", "spotify_uri", "source_track_id",
    "museum_id", "title", "artist", "album", "ms_played", "start_reason",
    "end_reason", "explicit_skip", "shuffle", "offline", "device_class",
    "os", "country", "social_listening", "session_context",
    "match_status", "match_method", "authority_status",
)


@dataclass(frozen=True)
class RecordBatch:
    batch_number: int
    batch_total: int
    start_offset: int
    end_offset: int
    records: list


def iter_record_batches(records, batch_size=DEFAULT_BATCH_SIZE):
    """Yield deterministic record slices with checkpoint-friendly offsets."""
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("Batch size must be a positive integer.")
    record_total = len(records)
    batch_total = (record_total + batch_size - 1) // batch_size
    for start in range(0, record_total, batch_size):
        end = min(start + batch_size, record_total)
        yield RecordBatch(
            batch_number=(start // batch_size) + 1,
            batch_total=batch_total,
            start_offset=start,
            end_offset=end,
            records=records[start:end],
        )


def archive_path():
    return os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "Output", "listening_archive.jsonl"
    ))


def _text(value):
    return "" if value is None else str(value).strip()


def _identity_text(value):
    value = unicodedata.normalize("NFKD", _text(value)).casefold()
    return " ".join(re.findall(r"[\w]+", value, flags=re.UNICODE))


def _optional_bool(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().casefold() in {"true", "false", "yes", "no"}:
        return value.strip().casefold() in {"true", "yes"}
    raise ValueError(f"{field} must be true, false, or absent.")


def build_collection_identity_indexes(collection):
    """Build all exact Collection lookups once for a scan/import run."""
    indexes = {
        "spotify_uri": {},
        "source_track_id": {},
        "museum_id": {},
        "title_artist": {},
    }
    if collection is None or getattr(collection, "empty", True):
        return indexes
    for row in collection.to_dict(orient="records"):
        if _text(row.get("Source")) != "Spotify":
            continue
        track_id = _text(row.get("Source Track ID"))
        museum_id = _text(row.get("Museum ID"))
        identity = (museum_id, track_id)
        if track_id:
            indexes["spotify_uri"][f"spotify:track:{track_id}"] = identity
            indexes["source_track_id"][track_id] = identity
        if museum_id:
            indexes["museum_id"][museum_id] = identity
        key = (_identity_text(row.get("Title")), _identity_text(row.get("Artist")))
        if all(key):
            indexes["title_artist"].setdefault(key, []).append(identity)
    return indexes


def collection_identity_indexes(collection):
    indexes = build_collection_identity_indexes(collection)
    return indexes["spotify_uri"], indexes["title_artist"]


def collection_uri_index(collection):
    """Compatibility helper returning URI -> Museum ID."""
    uri_index, _ = collection_identity_indexes(collection)
    return {uri: identity[0] for uri, identity in uri_index.items()}


def resolve_identity(raw, collection=None, uri_index=None, identity_indexes=None):
    uri = _text(raw.get("spotify_uri") or raw.get("spotify_track_uri"))
    title = _text(raw.get("title") or raw.get("track_title"))
    artist = _text(raw.get("artist"))
    if identity_indexes is not None:
        uri_index = identity_indexes["spotify_uri"]
        title_artist = identity_indexes["title_artist"]
        exact = uri_index.get(uri)
    elif uri_index is not None:
        exact = uri_index.get(uri)
        if isinstance(exact, str):
            exact = (exact, uri.rsplit(":", 1)[-1] if uri else "")
        title_artist = {}
    else:
        identity_indexes = build_collection_identity_indexes(collection)
        uri_index = identity_indexes["spotify_uri"]
        title_artist = identity_indexes["title_artist"]
        exact = uri_index.get(uri)
    if uri and exact:
        return exact[0], exact[1], "exact_uri", "spotify_uri"
    if uri:
        return "", uri.rsplit(":", 1)[-1], "unresolved", "none"
    key = (_identity_text(title), _identity_text(artist))
    matches = title_artist.get(key, []) if all(key) else []
    if len(matches) == 1:
        return matches[0][0], matches[0][1], "exact_title_artist", "normalized_title_artist"
    if len(matches) > 1:
        return "", "", "ambiguous", "normalized_title_artist"
    return "", "", "unresolved", "none"


def _parse_ms_played(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("Milliseconds played must be a non-negative integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Milliseconds played must be a non-negative integer.") from error
    if parsed < 0 or str(value).strip() not in {str(parsed), f"{parsed}.0"}:
        raise ValueError("Milliseconds played must be a non-negative integer.")
    return parsed


def normalize_event(raw, source=None, source_file="", source_version="",
                    uri_index=None, imported_at=None, collection=None,
                    authority_status="historical_authoritative",
                    identity_indexes=None):
    if not isinstance(raw, dict):
        raise ValueError("Listening event must be an object.")
    source_type = _text(source or raw.get("source_type"))
    timestamp = _text(raw.get("event_timestamp") or raw.get("timestamp") or raw.get("ts"))
    if not source_type or not timestamp:
        raise ValueError("Listening event source type and timestamp are required.")
    if authority_status not in AUTHORITY_STATUSES:
        raise ValueError("Listening event authority status is invalid.")
    source_file = _text(raw.get("source_file") or source_file)
    source_version = _text(raw.get("source_schema_version") or source_version)
    uri = _text(raw.get("spotify_uri") or raw.get("spotify_track_uri"))
    played = _parse_ms_played(raw.get("ms_played", raw.get("milliseconds_played", "")))
    museum_id, source_track_id, match_status, match_method = resolve_identity(
        raw, collection=collection, uri_index=uri_index,
        identity_indexes=identity_indexes,
    )
    title = _text(raw.get("title") or raw.get("track_title"))
    artist = _text(raw.get("artist")); album = _text(raw.get("album"))
    source_record_id = _text(raw.get("source_record_id"))
    stable = {
        "source_type": source_type, "source_record_id": source_record_id,
        "event_timestamp": timestamp,
        "end_timestamp": _text(raw.get("end_timestamp")), "spotify_uri": uri,
        "title": title, "artist": artist, "album": album, "ms_played": played,
        "start_reason": _text(raw.get("start_reason")),
        "end_reason": _text(raw.get("end_reason")),
    }
    event_id = hashlib.sha256(json.dumps(
        stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    event = {
        "event_id": event_id, "archive_version": ARCHIVE_VERSION,
        "source_type": source_type, "source_file": source_file,
        "source_record_id": source_record_id,
        "source_schema_version": source_version,
        "imported_at": imported_at or datetime.now(timezone.utc).isoformat(),
        "event_timestamp": timestamp, "end_timestamp": stable["end_timestamp"],
        "spotify_uri": uri, "source_track_id": source_track_id,
        "museum_id": museum_id, "title": title, "artist": artist, "album": album,
        "ms_played": played, "start_reason": stable["start_reason"],
        "end_reason": stable["end_reason"],
        "explicit_skip": _optional_bool(raw.get("explicit_skip"), "explicit_skip"),
        "shuffle": _optional_bool(raw.get("shuffle"), "shuffle"),
        "offline": _optional_bool(raw.get("offline", raw.get("downloaded")), "offline"),
        "device_class": _text(raw.get("device_class") or raw.get("device") or raw.get("platform")),
        "os": _text(raw.get("os")), "country": _text(raw.get("country")),
        "social_listening": _optional_bool(
            raw.get("social_listening"), "social_listening"
        ),
        "session_context": _text(raw.get("session_context")),
        "match_status": match_status, "match_method": match_method,
        "authority_status": authority_status,
    }
    validate_event(event)
    return event


def _upgrade_event(event):
    version = event.get("archive_version")
    if version == ARCHIVE_VERSION:
        return event
    if version == "2":
        upgraded = dict(event)
        upgraded["archive_version"] = ARCHIVE_VERSION
        upgraded["social_listening"] = None
        upgraded["session_context"] = ""
        return upgraded
    if version != "1":
        return event
    upgraded = {
        "event_id": event.get("event_id", ""), "archive_version": ARCHIVE_VERSION,
        "source_type": event.get("source", ""),
        "source_file": event.get("source_file", "") or "legacy-archive-v1",
        "source_record_id": "legacy-v1:" + event.get("event_id", ""),
        "source_schema_version": event.get("source_version", ""),
        "imported_at": event.get("imported_at", ""),
        "event_timestamp": event.get("event_timestamp", ""),
        "end_timestamp": event.get("end_timestamp", ""),
        "spotify_uri": event.get("spotify_uri", ""),
        "source_track_id": _text(event.get("spotify_uri", "")).rsplit(":", 1)[-1]
        if event.get("spotify_uri") else "", "museum_id": event.get("museum_id", ""),
        "title": event.get("title", ""), "artist": event.get("artist", ""),
        "album": event.get("album", ""), "ms_played": event.get("ms_played"),
        "start_reason": event.get("start_reason", ""), "end_reason": event.get("end_reason", ""),
        "explicit_skip": event.get("explicit_skip"), "shuffle": event.get("shuffle"),
        "offline": event.get("offline"), "device_class": event.get("device_class", ""),
        "os": event.get("os", ""), "country": event.get("country", ""),
        "social_listening": None, "session_context": "",
        "match_status": event.get("match_status", "unresolved"),
        "match_method": "spotify_uri" if event.get("match_status") == "exact_uri" else "none",
        "authority_status": "historical_authoritative",
    }
    return upgraded


def validate_event(event):
    if not isinstance(event, dict) or set(event) != set(EVENT_FIELDS):
        raise ValueError("Normalized listening event schema is invalid.")
    if not re.fullmatch(r"[0-9a-f]{64}", _text(event["event_id"])):
        raise ValueError("Normalized listening Event ID is invalid.")
    if not event["source_type"] or not event["event_timestamp"] or not event["imported_at"]:
        raise ValueError("Normalized listening event identity or provenance is incomplete.")
    if event["match_status"] not in MATCH_STATUSES or event["match_method"] not in MATCH_METHODS:
        raise ValueError("Normalized listening identity status is invalid.")
    if event["authority_status"] not in AUTHORITY_STATUSES:
        raise ValueError("Normalized listening authority status is invalid.")
    if event["source_type"] == "spotify_user_export" and (
        not event["source_file"] or not event["source_record_id"]
    ):
        raise ValueError("Spotify export events require source-file and record provenance.")
    if event["match_status"] in {"exact_uri", "exact_title_artist"} and not event["museum_id"]:
        raise ValueError("Resolved matches require a Museum ID.")
    _parse_ms_played(event["ms_played"])
    for field in ("explicit_skip", "shuffle", "offline", "social_listening"):
        _optional_bool(event[field], field)
    return True


def load_events(path=None):
    path = path or archive_path()
    if not os.path.exists(path):
        return []
    events = []
    try:
        with open(path, "r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                decoded = json.loads(line)
                if not isinstance(decoded, dict):
                    raise ValueError(
                        f"Listening Archive line {line_number} is not an event object."
                    )
                event = _upgrade_event(decoded)
                validate_event(event)
                events.append(event)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Listening Archive is malformed or unreadable: {error}") from error
    if len({event["event_id"] for event in events}) != len(events):
        raise ValueError("Listening Archive contains duplicate Event IDs.")
    if events != sorted(events, key=lambda item: (item["event_timestamp"], item["event_id"])):
        raise ValueError("Listening Archive event ordering is invalid.")
    return events


def _collision_view(event):
    # A copied/re-exported identical record may arrive under another filename.
    return {key: value for key, value in event.items()
            if key not in {"imported_at", "source_file", "source_schema_version"}}


def import_events(raw_events, source, collection=None, source_file="",
                  source_version="", path=None, imported_at=None,
                  authority_status="historical_authoritative",
                  batch_size=DEFAULT_BATCH_SIZE):
    path = path or archive_path()
    existing = load_events(path)
    by_id = {event["event_id"]: event for event in existing}
    identity_indexes = build_collection_identity_indexes(collection)
    added = 0
    for batch in iter_record_batches(raw_events, batch_size):
        for raw in batch.records:
            event = normalize_event(
                raw, source, source_file, source_version,
                collection=collection, imported_at=imported_at,
                authority_status=authority_status,
                identity_indexes=identity_indexes,
            )
            prior = by_id.get(event["event_id"])
            if prior is not None:
                if _collision_view(prior) != _collision_view(event):
                    raise ValueError("Deterministic Event ID collision has conflicting content.")
                continue
            by_id[event["event_id"]] = event; added += 1
    ordered = sorted(by_id.values(), key=lambda item: (item["event_timestamp"], item["event_id"]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as output:
            for event in ordered:
                validate_event(event)
                output.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            try: os.remove(temporary)
            except OSError: pass
        raise
    return {"added": added, "existing": len(existing), "total": len(ordered),
            "already_imported": len(raw_events) - added}


def classify_playback(event, duration_ms=None):
    played = event.get("ms_played")
    end_reason = _text(event.get("end_reason")).casefold()
    if event.get("explicit_skip") is True or end_reason in {
        "forward button", "fwdbtn", "track skipped", "forward"
    }:
        return "explicit_skip"
    if end_reason in {"track completed", "endplay", "trackdone", "track done"}:
        return "completed_play"
    if duration_ms and played is not None and played >= int(duration_ms) * 0.9:
        return "completed_play"
    if end_reason in INTERRUPTION_END_REASONS:
        return "interrupted_or_other"
    if played is not None and played >= 30000:
        return "meaningful_play"
    if played is not None and played < 30000:
        return "short_play"
    return "interrupted_or_other"
