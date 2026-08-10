"""Read-only Spotify export discovery, preview, and confirmed Museum import."""

import hashlib
import io
import json
import os
import zipfile
from pathlib import PurePosixPath

from listening_archive import (
    DEFAULT_BATCH_SIZE, build_collection_identity_indexes, import_events,
    iter_record_batches, load_events, normalize_event,
)


PLAYBACK_HINTS = {
    "endTime", "artistName", "trackName", "msPlayed", "timestamp", "ts",
    "spotify_track_uri", "spotifyUri", "ms_played", "milliseconds_played",
}
PLAYBACK_CONTENT_HINTS = PLAYBACK_HINTS - {"endTime", "timestamp", "ts"}
PLAYBACK_CONTENT_HINTS.update({
    "album", "albumName", "artist", "device", "end_reason",
    "master_metadata_album_artist_name", "master_metadata_track_name",
    "reason_end", "reason_start", "spotify_uri", "track_title", "uri",
})
PLAYBACK_TIME_HINTS = {"endTime", "end_time", "event_timestamp", "timestamp", "ts"}
TELEMETRY_HINTS = {"latency", "buffer", "experiment", "drm", "requestTiming"}
RICH_PLAYBACK_TIME_HINTS = {"timestamp_utc"}
RICH_PLAYBACK_DURATION_HINTS = {"message_ms_played"}
RICH_PLAYBACK_CONTENT_HINTS = {
    "message_content_uri", "message_displayed_content_uri", "message_audio_id",
}
MAX_ZIP_JSON_MEMBERS = 5000
MAX_ZIP_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


def _emit_progress(progress, event, **details):
    if progress is not None:
        progress(event, **details)


def default_input_directory():
    return os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "Input", "Spotify Data"
    ))


def discover_default_archives(path=None):
    path = path or default_input_directory()
    if not os.path.isdir(path):
        return []
    return sorted(
        os.path.join(path, name) for name in os.listdir(path)
        if name.lower().endswith(".zip") and os.path.isfile(os.path.join(path, name))
    )


def _first(record, *names):
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def _bool(record, *names):
    value = _first(record, *names)
    if isinstance(value, str):
        if value.casefold() in {"true", "yes"}: return True
        if value.casefold() in {"false", "no"}: return False
    return value


def _record_fingerprint(record):
    return hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def classify_source_record(record):
    if not isinstance(record, dict):
        return "malformed"
    keys = set(record)
    if (keys & RICH_PLAYBACK_TIME_HINTS
            and keys & RICH_PLAYBACK_DURATION_HINTS
            and keys & RICH_PLAYBACK_CONTENT_HINTS):
        return "rich_playback"
    if keys & TELEMETRY_HINTS and not keys & PLAYBACK_CONTENT_HINTS:
        return "technical_telemetry"
    if keys & PLAYBACK_CONTENT_HINTS or keys & PLAYBACK_TIME_HINTS:
        if not keys & PLAYBACK_CONTENT_HINTS:
            return "unsupported"
        return "museum_playback"
    if keys & TELEMETRY_HINTS:
        return "technical_telemetry"
    return "unsupported"


def adapt_playback_record(record, classification=None):
    """Map simple or rich Spotify playback records without inventing fields."""
    classification = classification or classify_source_record(record)
    if classification not in {"museum_playback", "rich_playback"}:
        raise ValueError("Record is not a recognized playback event.")
    adapted = {
        "event_timestamp": _first(
            record, "timestamp", "timestamp_utc", "ts", "endTime", "end_time"
        ),
        "end_timestamp": _first(record, "end_timestamp", "endTime", "end_time"),
        "spotify_uri": _first(
            record, "spotify_track_uri", "spotifyUri", "spotify_uri", "uri",
            "message_content_uri", "message_displayed_content_uri",
        ),
        "title": _first(record, "master_metadata_track_name", "trackName", "track_title", "title"),
        "artist": _first(record, "master_metadata_album_artist_name", "artistName", "artist"),
        "album": _first(record, "master_metadata_album_album_name", "albumName", "album"),
        "ms_played": _first(
            record, "ms_played", "msPlayed", "milliseconds_played",
            "message_ms_played",
        ),
        "start_reason": _first(
            record, "reason_start", "start_reason", "reasonStart",
            "message_reason_start",
        ),
        "end_reason": _first(
            record, "reason_end", "end_reason", "reasonEnd", "message_reason_end"
        ),
        "explicit_skip": _bool(record, "skipped", "explicit_skip"),
        "shuffle": _bool(record, "shuffle", "shuffle_state", "message_shuffle"),
        "offline": _bool(
            record, "offline", "downloaded", "is_offline",
            "message_content_is_downloaded",
        ),
        "device_class": _first(
            record, "device_class", "device", "platform", "context_device_type",
            "context_device_model", "context_device_manufacturer",
        ),
        "os": _first(record, "os", "operating_system", "context_os_name"),
        "country": _first(record, "country", "conn_country", "context_conn_country"),
        "social_listening": _bool(
            record, "social_listening", "message_social_listening"
        ),
        "session_context": _first(
            record, "session_context", "message_context_uri", "context_uri"
        ),
        "source_record_id": _first(record, "event_id", "id") or _record_fingerprint(record),
    }
    return {key: value for key, value in adapted.items() if value is not None}


def _records_from_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("events", "playbackEvents", "streamingHistory", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _safe_zip_member(name):
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and (not path.parts or ":" not in path.parts[0])
    )


def _zip_documents(path, source_index, source_total, progress=None):
    archive_name = os.path.basename(path)
    archive_context = {
        "source_index": source_index,
        "source_total": source_total,
        "source_name": archive_name,
        "source_kind": "zip",
        "member_index": None,
        "member_total": None,
        "member_name": None,
    }
    _emit_progress(
        progress, "archive_started", archive_index=source_index,
        archives_total=source_total, archive_name=archive_name,
    )
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = [item for item in archive.infolist()
                       if not item.is_dir() and item.filename.lower().endswith(".json")]
            _emit_progress(
                progress, "archive_members", archive_index=source_index,
                archives_total=source_total, archive_name=archive_name,
                json_members_total=len(members),
            )
            if len(members) > MAX_ZIP_JSON_MEMBERS:
                _emit_progress(
                    progress, "archive_failed", archive_index=source_index,
                    archives_total=source_total, archive_name=archive_name,
                    reason="too_many_json_members",
                )
                yield archive_name, None, archive_context
                return
            if sum(item.file_size for item in members) > MAX_ZIP_TOTAL_BYTES:
                _emit_progress(
                    progress, "archive_failed", archive_index=source_index,
                    archives_total=source_total, archive_name=archive_name,
                    reason="json_members_too_large",
                )
                yield archive_name, None, archive_context
                return
            for member_index, member in enumerate(members, 1):
                member_name = os.path.basename(member.filename)
                label = f"{archive_name}!{member_name}"
                context = {
                    **archive_context,
                    "member_index": member_index,
                    "member_total": len(members),
                    "member_name": member_name,
                }
                _emit_progress(
                    progress, "member_started", archive_index=source_index,
                    archives_total=source_total, archive_name=archive_name,
                    member_index=member_index, member_total=len(members),
                    member_name=member_name,
                )
                if (not _safe_zip_member(member.filename)
                        or member.file_size > MAX_ZIP_MEMBER_BYTES):
                    _emit_progress(
                        progress, "member_failed", archive_name=archive_name,
                        member_index=member_index, member_total=len(members),
                        member_name=member_name, reason="unsafe_or_too_large",
                    )
                    yield label, None, context
                    continue
                try:
                    with archive.open(member, "r") as binary:
                        with io.TextIOWrapper(binary, encoding="utf-8-sig") as source:
                            payload = json.load(source)
                except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError):
                    _emit_progress(
                        progress, "member_failed", archive_name=archive_name,
                        member_index=member_index, member_total=len(members),
                        member_name=member_name, reason="unreadable_json",
                    )
                    yield label, None, context
                    continue
                records = _records_from_payload(payload)
                _emit_progress(
                    progress, "member_ready", archive_name=archive_name,
                    member_index=member_index, member_total=len(members),
                    member_name=member_name, records_total=len(records),
                )
                yield label, records, context
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        _emit_progress(
            progress, "archive_failed", archive_index=source_index,
            archives_total=source_total, archive_name=archive_name,
            reason="unreadable_archive",
        )
        yield archive_name, None, archive_context


def _json_document(path, source_index, source_total, progress=None):
    source_name = os.path.basename(path)
    context = {
        "source_index": source_index,
        "source_total": source_total,
        "source_name": source_name,
        "source_kind": "json",
        "member_index": None,
        "member_total": None,
        "member_name": source_name,
    }
    _emit_progress(
        progress, "json_source_started", source_index=source_index,
        sources_total=source_total, source_name=source_name,
    )
    try:
        with open(path, "r", encoding="utf-8-sig") as source:
            records = _records_from_payload(json.load(source))
            _emit_progress(
                progress, "member_ready", archive_name=None,
                member_index=None, member_total=None, member_name=source_name,
                records_total=len(records),
            )
            return source_name, records, context
    except (OSError, UnicodeError, json.JSONDecodeError):
        _emit_progress(
            progress, "json_source_failed", source_index=source_index,
            sources_total=source_total, source_name=source_name,
        )
        return source_name, None, context


def _source_paths(source_path):
    requested = source_path if isinstance(source_path, (list, tuple)) else [source_path]
    paths = []
    for value in requested:
        path = os.path.abspath(os.path.expanduser(str(value)))
        if os.path.isfile(path):
            if path.lower().endswith((".json", ".zip")):
                paths.append(path)
            continue
        if not os.path.isdir(path):
            raise ValueError("Import source does not exist or is not accessible.")
        paths.extend(sorted(
            os.path.join(root, name)
            for root, _, names in os.walk(path)
            for name in names if name.lower().endswith((".json", ".zip"))
        ))
    return paths


def _source_documents(paths, progress=None):
    source_total = len(paths)
    for source_index, path in enumerate(paths, 1):
        if path.lower().endswith(".zip"):
            yield from _zip_documents(path, source_index, source_total, progress)
        else:
            yield _json_document(path, source_index, source_total, progress)


def scan_import(source_path, collection, archive_file=None, progress=None,
                batch_size=DEFAULT_BATCH_SIZE):
    archive_file = archive_file or None
    paths = _source_paths(source_path)
    existing_ids = {event["event_id"] for event in load_events(archive_file)}
    identity_indexes = build_collection_identity_indexes(collection)
    schema_classification_cache = {}
    recognized_files = []; candidates = []; malformed = 0; telemetry = 0; unsupported = 0
    exact_uri = 0; title_artist_only = 0; rich_playback = 0
    exact_title_artist = 0; resolved = 0; ambiguous = 0; unresolved = 0
    for source_label, records, context in _source_documents(paths, progress):
        if records is None:
            malformed += 1
            if context["member_index"] is not None:
                _emit_progress(
                    progress, "member_complete", **context,
                    playback_records_found=len(candidates),
                    technical_telemetry_ignored=telemetry,
                )
            continue
        file_candidates = []
        file_resolved = 0; file_unresolved = 0; file_ambiguous = 0
        for batch in iter_record_batches(records, batch_size):
            for record in batch.records:
                schema_key = frozenset(record) if isinstance(record, dict) else None
                classification = schema_classification_cache.get(schema_key)
                if classification is None:
                    classification = classify_source_record(record)
                    schema_classification_cache[schema_key] = classification
                if classification == "technical_telemetry":
                    telemetry += 1
                elif classification == "unsupported":
                    unsupported += 1
                elif classification == "malformed":
                    malformed += 1
                else:
                    try:
                        raw = adapt_playback_record(record, classification)
                        event = normalize_event(
                            raw, "spotify_user_export", source_label, "auto",
                            collection=collection, imported_at="preview",
                            identity_indexes=identity_indexes,
                        )
                    except ValueError:
                        malformed += 1
                    else:
                        if classification == "rich_playback":
                            rich_playback += 1
                        raw["_preview_event_id"] = event["event_id"]
                        file_candidates.append(raw)
                        if event["spotify_uri"]: exact_uri += 1
                        else: title_artist_only += 1
                        if event["match_status"] == "exact_title_artist":
                            exact_title_artist += 1; resolved += 1; file_resolved += 1
                        elif event["match_status"] == "exact_uri":
                            resolved += 1; file_resolved += 1
                        elif event["match_status"] == "ambiguous":
                            ambiguous += 1; file_ambiguous += 1
                        elif event["match_status"] == "unresolved":
                            unresolved += 1; file_unresolved += 1
            _emit_progress(
                progress, "batch_complete", **context,
                batch_number=batch.batch_number, batch_total=batch.batch_total,
                records_processed=batch.end_offset, records_total=len(records),
                playback_records_found=len(file_candidates),
                resolved=file_resolved, unresolved=file_unresolved,
                ambiguous=file_ambiguous,
                technical_telemetry_ignored=telemetry,
            )
        if file_candidates:
            recognized_files.append(source_label)
            candidates.extend((source_label, raw) for raw in file_candidates)
        _emit_progress(
            progress, "member_complete", **context,
            playback_records_found=len(candidates),
            technical_telemetry_ignored=telemetry,
        )
    already = sum(1 for _, raw in candidates if raw["_preview_event_id"] in existing_ids)
    return {
        "source_basenames": [os.path.basename(path) for path in paths],
        "recognized_files": recognized_files,
        "candidates": candidates, "files_recognized": len(recognized_files),
        "playback_events": len(candidates), "events_with_uri": exact_uri,
        "rich_playback": rich_playback,
        "title_artist_only": title_artist_only, "exact_title_artist": exact_title_artist,
        "resolved": resolved,
        "ambiguous": ambiguous, "unresolved": unresolved, "malformed": malformed,
        "technical_telemetry_ignored": telemetry, "unsupported_ignored": unsupported,
        "already_imported": already,
    }


def commit_import(preview, collection, archive_file=None, imported_at=None,
                  batch_size=DEFAULT_BATCH_SIZE):
    """Commit exactly the previously scanned candidates, grouped by source file."""
    records = []
    for source_label, raw in preview["candidates"]:
        cleaned = {key: value for key, value in raw.items() if not key.startswith("_preview_")}
        cleaned["source_file"] = os.path.basename(source_label)
        cleaned["source_schema_version"] = "auto"
        records.append(cleaned)
    return import_events(
        records, "spotify_user_export", collection, path=archive_file,
        imported_at=imported_at, authority_status="historical_authoritative",
        batch_size=batch_size,
    )
