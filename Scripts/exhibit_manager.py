"""Versioned exhibit definitions and privacy-preserving derived exhibit results.

Automatic exhibits are saved queries.  Their contents are always recalculated from
the Collection, listening archive, and manifest; listening events are never copied
into exhibits.json.
"""

import calendar
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from inspection_manager import inspect_album, inspect_artist, normalize_search
from listening_archive import classify_playback
from profile_engine import ProfileEngine, TIMEZONE_POLICY, format_count, format_duration, format_span


EXHIBIT_VERSION = "2"
EXHIBIT_TYPES = {"automatic", "generated", "curated"}
EXHIBIT_ID_PATTERN = re.compile(r"^EXH-[0-9a-f]{32}$")
MUSEUM_ID_PATTERN = re.compile(r"^MMT-\d{6}$")
MIN_RATE_SAMPLE = 5
CATEGORIES = {
    "Featured", "Listening", "Artists", "Albums", "Time", "Behavior",
    "Devices & Context", "Preservation", "Generated", "Curated",
}
DEPENDENCIES = {
    "artifact_identity", "artist_identity", "album_identity",
    "collection_metadata", "event_timestamp", "listening_events",
    "manifest_occurrences", "on_repeat_snapshots", "playback_context",
}
FIELDS = {
    "exhibit_version", "exhibit_id", "display_number", "title", "description",
    "type", "created_at", "updated_at", "sort_order", "rule", "artifact_ids",
    "artist_constraint", "album_constraint", "date_range", "notes", "visible",
    "dependencies", "category", "featured", "display_preferences",
}


def _spec(key, title, metric, category, entity="artifact", description="",
          featured=False, **rule):
    return {
        "key": key, "title": title, "metric": metric, "category": category,
        "entity": entity, "description": description, "featured": featured,
        "rule": rule,
    }


AUTOMATIC_CATALOG = (
    _spec("most-played-tracks", "Most-Played Tracks", "most_played_tracks",
          "Featured", featured=True,
          description="Tracks ranked by recorded playback-event count."),
    _spec("most-played-artists", "Most-Played Artists", "most_played_artists",
          "Featured", "artist", featured=True,
          description="Preserved artist credits ranked by recorded playback-event count."),
    _spec("most-played-albums", "Most-Played Albums", "most_played_albums",
          "Featured", "album", featured=True,
          description="Albums ranked by recorded playback-event count."),
    _spec("artist-listening-time", "Artists by Recorded Listening Time", "artist_listening_time",
          "Artists", "artist", description="Preserved artist credits ranked by summed recorded milliseconds."),
    _spec("artist-relationships", "Longest Recorded Artist Relationships", "artist_relationships",
          "Artists", "artist", description="Preserved artist credits ranked by their span of recorded listening history."),
    _spec("album-listening-time", "Albums by Recorded Listening Time", "album_listening_time",
          "Albums", "album", description="Albums ranked by summed recorded milliseconds."),
    _spec("album-completions", "Most Completed Albums", "album_completions",
          "Albums", "album", description="Albums ranked by completed-play classifications."),
    _spec("most-listening-time", "Most Recorded Listening Time", "most_listening_time",
          "Listening", description="Tracks ranked by summed recorded milliseconds."),
    _spec("most-meaningful", "Most Meaningful Plays", "most_meaningful_plays",
          "Listening", description="Tracks ranked by events with at least 30 seconds recorded."),
    _spec("most-completed", "Most Completed Plays", "most_completed_plays",
          "Listening", description="Tracks ranked by completed-play classifications."),
    _spec("longest-relationships", "Longest Recorded Relationships", "longest_relationships",
          "Listening", featured=True,
          description="Tracks ranked by the span between first and latest recorded listen."),
    _spec("most-consistent", "Most Consistent Listening", "most_consistent",
          "Listening", description="Tracks ranked by distinct recorded calendar months."),
    _spec("returned-after-gap", "Returned After a Long Gap", "returned_after_gap",
          "Listening", description="Tracks revisited after a gap of at least 120 days.", gap_days=120),
    _spec("longest-gaps", "Longest Gaps Between Listens", "longest_gaps",
          "Listening", description="Tracks ranked by their longest interval between recorded listens."),
    _spec("explicit-skips", "Most Explicitly Skipped", "most_explicit_skips",
          "Behavior", description="Tracks ranked by explicit skip count; rates require five events."),
    _spec("natural-completions", "Most Naturally Completed", "most_natural_completions",
          "Behavior", description="Tracks ranked by recorded natural completion count."),
    _spec("direct-selection", "Started Through Direct Selection", "direct_selection",
          "Behavior", description="Tracks ranked by direct-selection starts."),
    _spec("shuffle-listening", "Most Heard on Shuffle", "shuffle_listening",
          "Behavior", description="Tracks ranked by events explicitly marked shuffle on."),
    _spec("late-night", "Late-Night Listening", "late_night", "Time",
          featured=True,
          description="Tracks heard from 00:00 through 04:59 in stored timestamp time."),
    _spec("morning", "Morning Listening", "morning_listening", "Time",
          description="Tracks heard from 05:00 through 11:59 in stored timestamp time."),
    _spec("evening", "Evening Listening", "evening_listening", "Time",
          description="Tracks heard from 17:00 through 23:59 in stored timestamp time."),
    _spec("weekend", "Weekend Listening", "weekend_listening", "Time",
          description="Tracks heard on recorded Saturdays and Sundays."),
    _spec("weekday", "Weekday Listening", "weekday_listening", "Time",
          description="Tracks heard on recorded Mondays through Fridays."),
    _spec("active-years", "Most Active Years", "listening_by_year", "Time", "year",
          description="Calendar years ranked by recorded playback-event count."),
    _spec("active-months", "Most Active Months", "listening_by_month", "Time", "month",
          description="Calendar months ranked by recorded playback-event count."),
    _spec("recent", "Recent Recorded Listening", "recent_listening", "Time",
          description="Tracks ordered by latest recorded listen."),
    _spec("mobile", "Mobile Listening", "mobile_listening", "Devices & Context",
          description="Tracks ranked by events whose recorded device class indicates mobile."),
    _spec("desktop", "Desktop Listening", "desktop_listening", "Devices & Context",
          description="Tracks ranked by events whose recorded device class indicates desktop."),
    _spec("offline", "Offline & Downloaded Listening", "offline_listening", "Devices & Context",
          description="Tracks ranked by events explicitly marked offline or downloaded."),
    _spec("playlist-mainstays", "Playlist Mainstays", "playlist_mainstays", "Preservation",
          description="Artifacts ranked by the number of distinct preserved playlists containing them."),
    _spec("repeated-collection", "Repeated in the Collection", "repeated_collection", "Preservation",
          description="Artifacts ranked by preserved playlist-occurrence count."),
    _spec("oldest-releases", "Oldest Preserved Releases", "oldest_releases", "Preservation",
          description="Artifacts ordered by known release date, oldest first."),
    _spec("newest-releases", "Newest Preserved Releases", "newest_releases", "Preservation",
          description="Artifacts ordered by known release date, newest first."),
    _spec("longest-tracks", "Longest Preserved Tracks", "longest_tracks", "Preservation",
          description="Artifacts ranked by known preserved duration."),
    _spec("shortest-tracks", "Shortest Preserved Tracks", "shortest_tracks", "Preservation",
          description="Artifacts ordered by known preserved duration, shortest first."),
)
RULE_METRICS = {item["metric"] for item in AUTOMATIC_CATALOG} | {"listening_in_year"}


def exhibit_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Output", "exhibits.json"))


def _automatic_id(catalog_key):
    return "EXH-" + uuid5(NAMESPACE_URL, "music-museum-toolkit/exhibit/" + catalog_key).hex


def _dependencies(exhibit_type, rule, artist="", album=""):
    dependencies = set()
    metric = rule.get("metric") if isinstance(rule, dict) else None
    if exhibit_type in {"automatic", "generated"}:
        dependencies.add("listening_events")
    if metric in {"most_played_artists", "artist_listening_time", "artist_relationships"} or artist:
        dependencies.add("artist_identity")
    if metric in {"most_played_albums", "album_listening_time", "album_completions"} or album:
        dependencies.update({"album_identity", "collection_metadata"})
    if metric in {
        "listening_by_year", "listening_by_month", "listening_in_year", "late_night",
        "morning_listening", "evening_listening", "weekend_listening",
        "weekday_listening", "recent_listening", "longest_relationships",
        "most_consistent", "returned_after_gap", "longest_gaps",
    }:
        dependencies.add("event_timestamp")
    if metric in {"playlist_mainstays", "repeated_collection"}:
        dependencies.add("manifest_occurrences")
    if metric in {
        "mobile_listening", "desktop_listening", "offline_listening",
        "shuffle_listening", "direct_selection",
    }:
        dependencies.add("playback_context")
    if metric in {
        "oldest_releases", "newest_releases", "longest_tracks", "shortest_tracks",
    } or artist or album:
        dependencies.add("collection_metadata")
    if metric and metric not in {"most_played_artists", "most_played_albums", "listening_by_year", "listening_by_month"}:
        dependencies.add("artifact_identity")
    return sorted(dependencies)


def _default_category(exhibit_type, rule):
    if exhibit_type == "curated":
        return "Curated"
    if exhibit_type == "generated":
        return "Generated"
    metric = rule.get("metric") if isinstance(rule, dict) else ""
    for spec in AUTOMATIC_CATALOG:
        if spec["metric"] == metric:
            return spec["category"]
    return "Listening"


def _upgrade(exhibit):
    if not isinstance(exhibit, dict):
        raise ValueError("Each exhibit must be an object.")
    upgraded = dict(exhibit)
    upgraded["exhibit_version"] = EXHIBIT_VERSION
    upgraded.setdefault("sort_order", upgraded.get("display_number"))
    upgraded.setdefault("artist_constraint", "")
    upgraded.setdefault("album_constraint", "")
    upgraded.setdefault("date_range", {})
    upgraded.setdefault("visible", True)
    upgraded.setdefault("category", _default_category(upgraded.get("type"), upgraded.get("rule", {})))
    upgraded.setdefault("featured", False)
    upgraded.setdefault("display_preferences", {})
    dependencies = upgraded.get("dependencies")
    if (not isinstance(dependencies, list) or not set(dependencies).issubset(DEPENDENCIES)):
        upgraded["dependencies"] = _dependencies(
            upgraded.get("type"), upgraded.get("rule", {}),
            upgraded.get("artist_constraint", ""), upgraded.get("album_constraint", ""),
        )
    return upgraded


def validate_exhibits(exhibits):
    if not isinstance(exhibits, list):
        raise ValueError("Exhibit data must be a list.")
    seen_ids = set()
    seen_numbers = set()
    for raw in exhibits:
        exhibit = _upgrade(raw)
        if set(exhibit) != FIELDS:
            raise ValueError("Exhibit schema is invalid.")
        if exhibit["exhibit_version"] != EXHIBIT_VERSION:
            raise ValueError("Exhibit version is unsupported.")
        if not EXHIBIT_ID_PATTERN.fullmatch(str(exhibit["exhibit_id"])):
            raise ValueError("Exhibit ID is invalid.")
        if exhibit["type"] not in EXHIBIT_TYPES:
            raise ValueError("Exhibit type is invalid.")
        if not isinstance(exhibit["display_number"], int) or exhibit["display_number"] < 1:
            raise ValueError("Exhibit display number is invalid.")
        if not isinstance(exhibit["sort_order"], int) or exhibit["sort_order"] < 1:
            raise ValueError("Exhibit sort order is invalid.")
        if exhibit["exhibit_id"] in seen_ids or exhibit["display_number"] in seen_numbers:
            raise ValueError("Exhibit IDs and display numbers must be unique.")
        if (not isinstance(exhibit["title"], str) or not exhibit["title"].strip()
                or not isinstance(exhibit["rule"], dict)):
            raise ValueError("Exhibit title or rule is invalid.")
        if not all(isinstance(exhibit[field], str) for field in (
                "description", "created_at", "updated_at", "artist_constraint",
                "album_constraint", "notes")):
            raise ValueError("Exhibit text or timestamp fields are invalid.")
        if not exhibit["created_at"] or not exhibit["updated_at"]:
            raise ValueError("Exhibit timestamps are required.")
        if (not isinstance(exhibit["date_range"], dict)
                or not isinstance(exhibit["visible"], bool)
                or not isinstance(exhibit["featured"], bool)
                or not isinstance(exhibit["display_preferences"], dict)
                or exhibit["category"] not in CATEGORIES):
            raise ValueError("Exhibit display metadata is invalid.")
        if (not isinstance(exhibit["artifact_ids"], list)
                or not all(isinstance(item, str) and MUSEUM_ID_PATTERN.fullmatch(item)
                           for item in exhibit["artifact_ids"])
                or len(set(exhibit["artifact_ids"])) != len(exhibit["artifact_ids"])):
            raise ValueError("Curated exhibit membership is invalid.")
        if exhibit["type"] != "curated" and exhibit["artifact_ids"]:
            raise ValueError("Only curated exhibits may persist explicit artifact membership.")
        if exhibit["type"] == "automatic" and exhibit["rule"].get("metric") not in RULE_METRICS:
            raise ValueError("Automatic exhibit rule is invalid.")
        if (exhibit["type"] == "generated"
                and not (exhibit["artist_constraint"] or exhibit["album_constraint"])):
            raise ValueError("Generated exhibits require an artist or album constraint.")
        if (not isinstance(exhibit["dependencies"], list)
                or len(set(exhibit["dependencies"])) != len(exhibit["dependencies"])
                or not set(exhibit["dependencies"]).issubset(DEPENDENCIES)):
            raise ValueError("Exhibit dependencies are invalid.")
        seen_ids.add(exhibit["exhibit_id"])
        seen_numbers.add(exhibit["display_number"])
    return True


def load_exhibits(path=None):
    path = path or exhibit_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as source:
            raw = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Exhibit data is malformed or unreadable: {error}") from error
    exhibits = [_upgrade(item) for item in raw] if isinstance(raw, list) else raw
    validate_exhibits(exhibits)
    return sorted(exhibits, key=lambda item: item["display_number"])


def create_exhibit(title, exhibit_type, description="", artifact_ids=None, rule=None,
                   exhibits=None, artist="", album="", notes="", category=None,
                   featured=False, display_preferences=None, exhibit_id=None):
    if exhibit_type not in EXHIBIT_TYPES:
        raise ValueError("Unsupported exhibit type.")
    title = str(title).strip()
    if not title:
        raise ValueError("Exhibit title is required.")
    exhibits = exhibits or []
    now = datetime.now(timezone.utc).isoformat()
    rule = dict(rule or {})
    exhibit = {
        "exhibit_version": EXHIBIT_VERSION,
        "exhibit_id": exhibit_id or "EXH-" + uuid4().hex,
        "display_number": max((item["display_number"] for item in exhibits), default=0) + 1,
        "title": title, "description": str(description).strip(), "type": exhibit_type,
        "created_at": now, "updated_at": now, "sort_order": len(exhibits) + 1,
        "rule": rule, "artifact_ids": list(artifact_ids or []),
        "artist_constraint": str(artist).strip(), "album_constraint": str(album).strip(),
        "date_range": {}, "notes": str(notes), "visible": True,
        "dependencies": _dependencies(exhibit_type, rule, artist, album),
        "category": category or _default_category(exhibit_type, rule),
        "featured": bool(featured), "display_preferences": dict(display_preferences or {}),
    }
    validate_exhibits([exhibit])
    return exhibit


def save_exhibits(exhibits, path=None):
    path = path or exhibit_path()
    upgraded = [_upgrade(item) for item in exhibits]
    validate_exhibits(upgraded)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as output:
            json.dump(upgraded, output, indent=2, ensure_ascii=False)
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
        raise
    return path


def reorder_exhibits(exhibits, ordered_ids):
    if set(ordered_ids) != {item["exhibit_id"] for item in exhibits} or len(ordered_ids) != len(exhibits):
        raise ValueError("Exhibit reorder must contain every Exhibit ID exactly once.")
    by_id = {item["exhibit_id"]: dict(item) for item in exhibits}
    now = datetime.now(timezone.utc).isoformat()
    result = []
    for number, exhibit_id in enumerate(ordered_ids, 1):
        item = by_id[exhibit_id]
        item["display_number"] = number
        item["sort_order"] = number
        item["updated_at"] = now
        result.append(item)
    validate_exhibits(result)
    return result


def add_curated_artifact(exhibit, museum_id):
    if exhibit.get("type") != "curated":
        raise ValueError("Only curated exhibits have explicit membership.")
    result = dict(exhibit)
    result["artifact_ids"] = list(exhibit["artifact_ids"])
    if museum_id not in result["artifact_ids"]:
        result["artifact_ids"].append(museum_id)
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def remove_curated_artifact(exhibit, museum_id):
    if exhibit.get("type") != "curated":
        raise ValueError("Only curated exhibits have explicit membership.")
    result = dict(exhibit)
    result["artifact_ids"] = [item for item in exhibit["artifact_ids"] if item != museum_id]
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def _parse_timestamp(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            pass
    return None


def _integer(value):
    try:
        result = int(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _new_stat():
    return {
        "events": 0, "listening_ms": 0, "known_ms": 0, "meaningful": 0,
        "completed": 0, "explicit_skips": 0, "natural_completions": 0,
        "direct_selection": 0, "late_night": 0, "morning": 0, "evening": 0,
        "weekend": 0, "weekday": 0, "mobile": 0, "desktop": 0,
        "offline": 0, "shuffle": 0, "first": None, "latest": None,
        "timestamps": [], "months": Counter(), "years": Counter(), "track_ids": set(),
    }


def _update_stat(stat, event, stamp, duration_ms=None):
    stat["events"] += 1
    played = _integer(event.get("ms_played"))
    if played is not None:
        stat["listening_ms"] += played
        stat["known_ms"] += 1
        if played >= 30000:
            stat["meaningful"] += 1
    classification = classify_playback(event, duration_ms)
    if classification == "completed_play":
        stat["completed"] += 1
    if classification == "explicit_skip":
        stat["explicit_skips"] += 1
    end_reason = str(event.get("end_reason", "")).strip().casefold()
    if end_reason in {"track completed", "trackdone", "track done", "endplay"}:
        stat["natural_completions"] += 1
    start_reason = str(event.get("start_reason", "")).strip().casefold()
    if start_reason in {"clicked track", "clickrow", "play button", "track clicked", "direct selection"}:
        stat["direct_selection"] += 1
    device = " ".join((str(event.get("device_class", "")), str(event.get("os", "")))).casefold()
    if any(token in device for token in ("mobile", "phone", "ios", "android")):
        stat["mobile"] += 1
    if any(token in device for token in ("desktop", "windows", "macos", "linux")):
        stat["desktop"] += 1
    if event.get("offline") is True:
        stat["offline"] += 1
    if event.get("shuffle") is True:
        stat["shuffle"] += 1
    if stamp:
        stat["timestamps"].append(stamp)
        stat["first"] = stamp if stat["first"] is None or stamp < stat["first"] else stat["first"]
        stat["latest"] = stamp if stat["latest"] is None or stamp > stat["latest"] else stat["latest"]
        stat["months"][stamp.strftime("%Y-%m")] += 1
        stat["years"][str(stamp.year)] += 1
        if stamp.hour <= 4:
            stat["late_night"] += 1
        if 5 <= stamp.hour <= 11:
            stat["morning"] += 1
        if 17 <= stamp.hour <= 23:
            stat["evening"] += 1
        if stamp.weekday() >= 5:
            stat["weekend"] += 1
        else:
            stat["weekday"] += 1


def build_exhibit_index(collection, events, manifest=None):
    """Build all exhibit aggregates in one pass over each source."""
    records = [] if collection is None or getattr(collection, "empty", True) else collection.to_dict("records")
    artifacts = {str(row.get("Museum ID", "")): dict(row) for row in records if row.get("Museum ID")}
    durations = {mid: _integer(row.get("Duration (ms)")) for mid, row in artifacts.items()}
    track_stats = defaultdict(_new_stat)
    artist_stats = defaultdict(_new_stat)
    album_stats = defaultdict(_new_stat)
    year_stats = defaultdict(_new_stat)
    month_stats = defaultdict(_new_stat)
    coverage = Counter()
    resolved_coverage = Counter()
    resolved_events = 0
    for event in events or []:
        coverage["total_events"] += 1
        for key in ("ms_played", "event_timestamp", "device_class", "offline", "shuffle", "start_reason", "end_reason", "explicit_skip"):
            if event.get(key) is not None and event.get(key) != "":
                coverage[key] += 1
        museum_id = str(event.get("museum_id", "") or "")
        match_status = str(event.get("match_status", "") or "")
        if not museum_id or museum_id not in artifacts or match_status in {"ambiguous", "unresolved"}:
            continue
        resolved_events += 1
        for key in ("ms_played", "event_timestamp", "device_class", "offline", "shuffle", "start_reason", "end_reason", "explicit_skip"):
            if event.get(key) is not None and event.get(key) != "":
                resolved_coverage[key] += 1
        if event.get("explicit_skip") is not None or event.get("end_reason"):
            resolved_coverage["explicit_skip_or_end_reason"] += 1
        if event.get("end_reason") or event.get("ms_played") is not None:
            resolved_coverage["completion_evidence"] += 1
        artifact = artifacts[museum_id]
        stamp = _parse_timestamp(event.get("event_timestamp"))
        track = track_stats[museum_id]
        track["track_ids"].add(museum_id)
        _update_stat(track, event, stamp, durations.get(museum_id))
        artist = str(artifact.get("Artist", "") or "").strip()
        if artist:
            artist_stats[artist]["track_ids"].add(museum_id)
            _update_stat(artist_stats[artist], event, stamp, durations.get(museum_id))
        album = str(artifact.get("Album", "") or "").strip()
        if album:
            album_key = (normalize_search(artist), normalize_search(album))
            album_stats[album_key]["track_ids"].add(museum_id)
            _update_stat(album_stats[album_key], event, stamp, durations.get(museum_id))
        if stamp:
            year = str(stamp.year)
            month = stamp.strftime("%Y-%m")
            year_stats[year]["track_ids"].add(museum_id)
            month_stats[month]["track_ids"].add(museum_id)
            _update_stat(year_stats[year], event, stamp, durations.get(museum_id))
            _update_stat(month_stats[month], event, stamp, durations.get(museum_id))
    manifest_occurrences = Counter()
    manifest_playlists = defaultdict(set)
    if manifest is not None and not getattr(manifest, "empty", True):
        for row in manifest.to_dict("records"):
            museum_id = str(row.get("Museum ID", "") or "")
            if museum_id not in artifacts:
                continue
            manifest_occurrences[museum_id] += 1
            playlist = str(row.get("Playlist ID", "") or row.get("Playlist Name", "") or "")
            if playlist:
                manifest_playlists[museum_id].add(playlist)
    return {
        "artifacts": artifacts, "track_stats": track_stats, "artist_stats": artist_stats,
        "album_stats": album_stats, "year_stats": year_stats, "month_stats": month_stats,
        "manifest_occurrences": manifest_occurrences, "manifest_playlists": manifest_playlists,
        "coverage": dict(coverage), "resolved_coverage": dict(resolved_coverage),
        "resolved_events": resolved_events,
        "total_events": len(events or []), "timezone_policy": TIMEZONE_POLICY,
        "profile_engine": ProfileEngine(collection, events, manifest),
    }


def _public_stat(stat):
    result = {key: stat[key] for key in (
        "events", "listening_ms", "known_ms", "meaningful", "completed",
        "explicit_skips", "natural_completions", "direct_selection", "late_night",
        "morning", "evening", "weekend", "weekday", "mobile", "desktop",
        "offline", "shuffle",
    )}
    result["first_recorded_listen"] = stat["first"].isoformat() if stat["first"] else ""
    result["latest_recorded_listen"] = stat["latest"].isoformat() if stat["latest"] else ""
    result["distinct_months"] = len(stat["months"])
    result["distinct_years"] = len(stat["years"])
    if stat["events"] >= MIN_RATE_SAMPLE:
        result["skip_rate"] = stat["explicit_skips"] / stat["events"]
        result["completion_rate"] = stat["completed"] / stat["events"]
    else:
        result["skip_rate"] = None
        result["completion_rate"] = None
    return result


def _track_row(index, museum_id):
    artifact = index["artifacts"][museum_id]
    return {
        "entity_type": "artifact", "entity_id": museum_id,
        "title": str(artifact.get("Title", "")), "artist": str(artifact.get("Artist", "")),
        "album": str(artifact.get("Album", "")), "artifact": artifact,
        **_public_stat(index["track_stats"].get(museum_id, _new_stat())),
    }


def _sort_rows(rows, key, reverse=True):
    return sorted(rows, key=lambda row: (
        -(row.get(key) or 0) if reverse else (row.get(key) or 0),
        normalize_search(row.get("title") or row.get("label") or row.get("entity_id")),
    ))


def _track_rows(index, metric):
    rows = [_track_row(index, mid) for mid in index["artifacts"]]
    field = {
        "most_played_tracks": "events", "most_listening_time": "listening_ms",
        "most_meaningful_plays": "meaningful", "most_completed_plays": "completed",
        "most_explicit_skips": "explicit_skips", "most_natural_completions": "natural_completions",
        "direct_selection": "direct_selection", "late_night": "late_night",
        "morning_listening": "morning", "evening_listening": "evening",
        "weekend_listening": "weekend", "weekday_listening": "weekday",
        "mobile_listening": "mobile", "desktop_listening": "desktop",
        "offline_listening": "offline", "shuffle_listening": "shuffle",
        "most_consistent": "distinct_months",
    }.get(metric)
    if field:
        return _sort_rows([row for row in rows if row[field] > 0], field)
    if metric in {"longest_relationships", "returned_after_gap", "longest_gaps"}:
        result = []
        for row in rows:
            timestamps = sorted(index["track_stats"].get(row["entity_id"], _new_stat())["timestamps"])
            gaps = [(right - left).total_seconds() / 86400 for left, right in zip(timestamps, timestamps[1:])]
            row["relationship_days"] = ((timestamps[-1] - timestamps[0]).total_seconds() / 86400) if len(timestamps) > 1 else 0
            row["longest_gap_days"] = max(gaps, default=0)
            result.append(row)
        if metric == "longest_relationships":
            return _sort_rows([row for row in result if row["relationship_days"] > 0], "relationship_days")
        threshold = 120 if metric == "returned_after_gap" else 0
        return _sort_rows([row for row in result if row["longest_gap_days"] >= threshold and row["longest_gap_days"] > 0], "longest_gap_days")
    if metric == "recent_listening":
        return sorted([row for row in rows if row["latest_recorded_listen"]],
                      key=lambda row: (row["latest_recorded_listen"], normalize_search(row["title"])), reverse=True)
    if metric in {"playlist_mainstays", "repeated_collection"}:
        for row in rows:
            mid = row["entity_id"]
            row["playlist_count"] = len(index["manifest_playlists"].get(mid, set()))
            row["occurrence_count"] = index["manifest_occurrences"].get(mid, 0)
        field = "playlist_count" if metric == "playlist_mainstays" else "occurrence_count"
        minimum = 1 if metric == "playlist_mainstays" else 2
        return _sort_rows([row for row in rows if row[field] >= minimum], field)
    if metric in {"longest_tracks", "shortest_tracks"}:
        for row in rows:
            row["duration_ms"] = _integer(row["artifact"].get("Duration (ms)"))
        known = [row for row in rows if row["duration_ms"] and row["duration_ms"] > 0]
        return _sort_rows(known, "duration_ms", reverse=metric == "longest_tracks")
    if metric in {"oldest_releases", "newest_releases"}:
        for row in rows:
            value = str(row["artifact"].get("Release Date", "") or "").strip()
            match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", value)
            row["release_date"] = value if match else ""
            row["release_sort"] = (
                int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0)
            ) if match else None
        known = [row for row in rows if row["release_sort"]]
        return sorted(known, key=lambda row: (row["release_sort"], normalize_search(row["title"])),
                      reverse=metric == "newest_releases")
    return []


def _entity_rows(index, entity_type, field="events"):
    source = index["artist_stats"] if entity_type == "artist" else index["album_stats"]
    rows = []
    for key, stat in source.items():
        if entity_type == "artist":
            title, artist, entity_id = key, key, key
        else:
            sample = index["artifacts"][next(iter(stat["track_ids"]))]
            title, artist = str(sample.get("Album", "")), str(sample.get("Artist", ""))
            entity_id = artist + "\x1f" + title
        row = {
            "entity_type": entity_type, "entity_id": entity_id, "title": title,
            "artist": artist, "artifact_count": len(stat["track_ids"]), **_public_stat(stat),
        }
        if stat["first"] and stat["latest"]:
            row["relationship_days"] = (stat["latest"] - stat["first"]).total_seconds() / 86400
        else:
            row["relationship_days"] = 0
        rows.append(row)
    return _sort_rows([row for row in rows if (row.get(field) or 0) > 0], field)


def _time_rows(index, unit):
    source = index["year_stats"] if unit == "year" else index["month_stats"]
    rows = []
    for label, stat in source.items():
        display = label if unit == "year" else f"{calendar.month_name[int(label[5:7])]} {label[:4]}"
        rows.append({
            "entity_type": unit, "entity_id": label, "title": display,
            "artist": "", "artifact_count": len(stat["track_ids"]), **_public_stat(stat),
        })
    return _sort_rows(rows, "events")


def _coverage(index, eligible, basis, source_field=None):
    return {
        "total_events": index["total_events"], "resolved_events": index["resolved_events"],
        "eligible_events": eligible, "basis": basis, "minimum_rate_sample": MIN_RATE_SAMPLE,
        "timezone_policy": index["timezone_policy"], "available_fields": dict(index["coverage"]),
        "source_field": source_field or "",
        "source_field_events": index["resolved_coverage"].get(source_field, 0) if source_field else None,
    }


def evaluate_automatic_exhibit(exhibit, index, limit=None):
    """Return structured, explainable results for one automatic definition."""
    if exhibit.get("type") != "automatic":
        return {"rows": [], "coverage": _coverage(index, 0, "not automatic"), "story": [], "entity_type": ""}
    metric = exhibit.get("rule", {}).get("metric")
    if metric == "most_played_artists":
        rows = _entity_rows(index, "artist")
    elif metric == "artist_listening_time":
        rows = _entity_rows(index, "artist", "listening_ms")
    elif metric == "artist_relationships":
        rows = _entity_rows(index, "artist", "relationship_days")
    elif metric == "most_played_albums":
        rows = _entity_rows(index, "album")
    elif metric == "album_listening_time":
        rows = _entity_rows(index, "album", "listening_ms")
    elif metric == "album_completions":
        rows = _entity_rows(index, "album", "completed")
    elif metric == "listening_by_year":
        rows = _time_rows(index, "year")
    elif metric == "listening_by_month":
        rows = _time_rows(index, "month")
    elif metric == "listening_in_year":
        year = str(exhibit.get("rule", {}).get("year", ""))
        rows = []
        for mid, stat in index["track_stats"].items():
            if stat["years"].get(year):
                row = _track_row(index, mid)
                row["period_events"] = stat["years"][year]
                rows.append(row)
        rows = _sort_rows(rows, "period_events")
    else:
        rows = _track_rows(index, metric)
    value_field = {
        "most_listening_time": "listening_ms", "artist_listening_time": "listening_ms",
        "album_listening_time": "listening_ms", "most_meaningful_plays": "meaningful",
        "most_completed_plays": "completed", "most_explicit_skips": "explicit_skips",
        "most_natural_completions": "natural_completions", "direct_selection": "direct_selection",
        "late_night": "late_night", "morning_listening": "morning",
        "evening_listening": "evening", "weekend_listening": "weekend",
        "weekday_listening": "weekday", "mobile_listening": "mobile",
        "desktop_listening": "desktop", "offline_listening": "offline",
        "shuffle_listening": "shuffle", "album_completions": "completed",
        "listening_in_year": "period_events",
    }.get(metric, "events")
    eligible = sum(row.get(value_field, 0) for row in rows)
    total_results = len(rows)
    limit = limit or _integer(exhibit.get("rule", {}).get("limit")) or 25
    rows = rows[:limit]
    entity_type = rows[0]["entity_type"] if rows else exhibit.get("rule", {}).get("entity", "artifact")
    basis = exhibit.get("description") or str(metric).replace("_", " ")
    story = [f"This exhibit has {total_results} eligible ranked result{'s' if total_results != 1 else ''} calculated from recorded data."]
    if rows:
        top = rows[0]
        metric_label = {
            "most_played_tracks": "recorded events", "most_played_artists": "recorded events",
            "most_played_albums": "recorded events", "most_listening_time": "of recorded listening",
            "artist_listening_time": "of recorded listening", "album_listening_time": "of recorded listening",
            "most_meaningful_plays": "meaningful plays", "most_completed_plays": "completed plays",
            "album_completions": "completed plays", "most_explicit_skips": "explicit skips",
            "most_natural_completions": "recorded natural completions", "direct_selection": "direct-selection starts",
            "shuffle_listening": "shuffle-on events", "offline_listening": "offline/downloaded events",
            "mobile_listening": "mobile events", "desktop_listening": "desktop events",
            "listening_in_year": "recorded events",
        }.get(metric)
        value = top.get(value_field, 0)
        if metric_label:
            shown = format_duration(value) if value_field == "listening_ms" else format_count(value)
            sentence = f"{top['title']} ranks first with {shown} {metric_label}"
            if value_field not in {"events", "listening_ms"}:
                sentence += f" across {format_count(top.get('events', 0))} recorded events"
            story.append(sentence + ".")
        elif metric == "longest_relationships":
            story.append(f"{top['title']} ranks first with {format_span(days=top.get('relationship_days', 0))} of recorded history.")
        else:
            story.append(f"{top['title']} is the highest-ranked result with {format_count(top.get('events', 0))} recorded events.")
    if metric in {"late_night", "morning_listening", "evening_listening", "weekend_listening", "weekday_listening"}:
        story.append(TIMEZONE_POLICY)
    source_field = {
        "most_listening_time": "ms_played", "artist_listening_time": "ms_played",
        "album_listening_time": "ms_played", "most_meaningful_plays": "ms_played",
        "most_completed_plays": "completion_evidence", "album_completions": "completion_evidence",
        "most_explicit_skips": "explicit_skip_or_end_reason",
        "most_natural_completions": "end_reason",
        "direct_selection": "start_reason", "late_night": "event_timestamp",
        "morning_listening": "event_timestamp", "evening_listening": "event_timestamp",
        "weekend_listening": "event_timestamp", "weekday_listening": "event_timestamp",
        "listening_by_year": "event_timestamp", "listening_by_month": "event_timestamp",
        "listening_in_year": "event_timestamp", "recent_listening": "event_timestamp",
        "longest_relationships": "event_timestamp", "artist_relationships": "event_timestamp",
        "returned_after_gap": "event_timestamp", "longest_gaps": "event_timestamp",
        "most_consistent": "event_timestamp", "mobile_listening": "device_class",
        "desktop_listening": "device_class", "offline_listening": "offline",
        "shuffle_listening": "shuffle",
    }.get(metric)
    return {"rows": rows, "coverage": _coverage(index, eligible, basis, source_field), "story": story, "entity_type": entity_type}


def automatic_results(exhibit, events):
    """Compatibility result shape for callers that do not have a Collection."""
    if exhibit.get("type") != "automatic":
        return []
    metric = exhibit.get("rule", {}).get("metric")
    totals = Counter()
    if metric == "most_played_tracks":
        for event in events:
            if event.get("museum_id"):
                totals[event["museum_id"]] += 1
    elif metric == "most_played_artists":
        for event in events:
            if event.get("artist"):
                totals[event["artist"]] += 1
    elif metric == "listening_by_year":
        for event in events:
            stamp = str(event.get("event_timestamp", ""))
            if re.match(r"^\d{4}", stamp):
                totals[stamp[:4]] += 1
    elif metric == "late_night":
        for event in events:
            match = re.search(r"[T ](\d{2}):", str(event.get("event_timestamp", "")))
            if match and int(match.group(1)) <= 4:
                totals[event.get("museum_id") or event.get("title") or "Unresolved"] += 1
    return sorted(totals.items(), key=lambda item: (-item[1], item[0]))


def generated_artist_results(exhibit, collection, events):
    if exhibit.get("type") != "generated" or not exhibit.get("artist_constraint"):
        return None
    return inspect_artist(collection, events, exhibit["artist_constraint"])


def generated_album_results(exhibit, collection, events):
    if exhibit.get("type") != "generated" or not exhibit.get("album_constraint"):
        return None
    return inspect_album(collection, events, exhibit["album_constraint"], exhibit.get("artist_constraint") or None)


def _legacy_support(spec, events):
    metric = spec["metric"]
    if metric == "most_played_tracks":
        return any(event.get("museum_id") for event in events)
    if metric == "most_played_artists":
        return any(event.get("artist") for event in events)
    if metric == "listening_by_year":
        return any(re.match(r"^\d{4}", str(event.get("event_timestamp", ""))) for event in events)
    if metric == "late_night":
        return any(re.search(r"[T ](?:0[0-4]):", str(event.get("event_timestamp", ""))) for event in events)
    return False


def _catalog_supported(candidate, index):
    result = evaluate_automatic_exhibit(candidate, index)
    metric = candidate.get("rule", {}).get("metric")
    if metric == "listening_by_year":
        return len(index["year_stats"]) >= 2
    if metric == "listening_by_month":
        return len(index["month_stats"]) >= 2
    if metric in {"oldest_releases", "newest_releases", "longest_tracks", "shortest_tracks"}:
        return len(result["rows"]) >= 2
    return bool(result["rows"])


def create_starter_exhibits(events, exhibits=None, collection=None, manifest=None):
    """Idempotently add every supported catalog definition without changing existing exhibits."""
    exhibits = [_upgrade(item) for item in list(exhibits or [])]
    index = build_exhibit_index(collection, events, manifest) if collection is not None else None
    existing_keys = {
        item.get("rule", {}).get("catalog_key") for item in exhibits if item.get("type") == "automatic"
    }
    existing_metrics = {
        item.get("rule", {}).get("metric") for item in exhibits if item.get("type") == "automatic"
    }
    for spec in AUTOMATIC_CATALOG:
        if spec["key"] in existing_keys:
            continue
        if spec["metric"] in existing_metrics and spec["metric"] in {
                "most_played_tracks", "most_played_artists", "listening_by_year", "late_night"}:
            continue
        rule = {"catalog_key": spec["key"], "metric": spec["metric"], "entity": spec["entity"], **spec["rule"]}
        candidate = create_exhibit(
            spec["title"], "automatic", spec["description"], rule=rule, exhibits=exhibits,
            category=spec["category"], featured=spec["featured"], exhibit_id=_automatic_id(spec["key"]),
        )
        supported = _catalog_supported(candidate, index) if index else _legacy_support(spec, events)
        if supported:
            exhibits.append(candidate)
            existing_keys.add(spec["key"])
            existing_metrics.add(spec["metric"])
    if index:
        years = sorted(index["year_stats"])
        for year in years:
            key = "listening-in-" + year
            if key in existing_keys:
                continue
            exhibits.append(create_exhibit(
                f"Listening in {year}", "automatic",
                f"Tracks ranked by recorded playback-event count during {year}.",
                rule={"catalog_key": key, "metric": "listening_in_year", "entity": "artifact", "year": year},
                exhibits=exhibits, category="Time", featured=year == years[-1],
                exhibit_id=_automatic_id(key),
            ))
            existing_keys.add(key)
    validate_exhibits(exhibits)
    return exhibits


initialize_automatic_exhibits = create_starter_exhibits


def affected_exhibits(exhibits, changed_dependencies):
    changed = set(changed_dependencies)
    return [item for item in exhibits if changed.intersection(item.get("dependencies", []))]
