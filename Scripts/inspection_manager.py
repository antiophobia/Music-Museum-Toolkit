"""Read-only human search and derived Artifact/Artist/Album statistics."""

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher

from listening_archive import classify_playback


def normalize_search(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def search_artifacts(collection, query, limit=20):
    needle = normalize_search(query)
    if not needle or collection is None or getattr(collection, "empty", True):
        return []
    tokens = needle.split(); ranked = []
    for _, row in collection.iterrows():
        title = normalize_search(row.get("Title")); artist = normalize_search(row.get("Artist"))
        album = normalize_search(row.get("Album")); museum = normalize_search(row.get("Museum ID"))
        track_id = str(row.get("Source Track ID", "")).strip()
        uri = f"spotify:track:{track_id}" if track_id else ""
        combined = f"{title} {artist} {album}".strip()
        if query.strip().casefold() == uri.casefold() or needle == museum: rank = 0
        elif needle in {f"{artist} {title}", f"{title} {artist}"}: rank = 1
        elif needle == title: rank = 2
        elif all(token in f"{title} {artist}" for token in tokens): rank = 3
        elif needle == artist: rank = 4
        elif needle == album: rank = 5
        elif any(value.startswith(needle) for value in (title, artist, album)): rank = 6
        elif all(token in combined for token in tokens) or needle in combined: rank = 7
        else:
            similarity = max(SequenceMatcher(None, needle, value).ratio()
                             for value in (title, f"{title} {artist}", artist, album) if value)
            if similarity < 0.72: continue
            rank = 8
        ranked.append((rank, title, artist, album, row.to_dict()))
    ranked.sort(key=lambda item: item[:4])
    return [item[-1] for item in ranked[:limit]]


def search_entities(collection, field, query):
    needle = normalize_search(query); values = set()
    if field not in {"Artist", "Album"} or not needle:
        return []
    for value in collection.get(field, []):
        text = str(value or "").strip(); normalized = normalize_search(text)
        if normalized == needle or normalized.startswith(needle) or needle in normalized:
            values.add(text)
    return sorted(values, key=lambda value: (normalize_search(value) != needle, normalize_search(value)))


def search_albums(collection, query):
    needle = normalize_search(query); albums = {}
    if not needle:
        return []
    for _, row in collection.iterrows():
        album = str(row.get("Album", "") or "").strip()
        artist = str(row.get("Artist", "") or "").strip()
        normalized = normalize_search(album)
        if normalized == needle or normalized.startswith(needle) or needle in normalized:
            key = (normalized, normalize_search(artist))
            item = albums.setdefault(key, {
                "album": album, "artist": artist, "artifact_count": 0,
            })
            item["artifact_count"] += 1
    return sorted(
        albums.values(),
        key=lambda item: (
            normalize_search(item["album"]) != needle,
            normalize_search(item["album"]), normalize_search(item["artist"]),
        ),
    )


def _parse_timestamp(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    for parser in (datetime.fromisoformat,):
        try: return parser(text)
        except ValueError: pass
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(text, pattern)
        except ValueError: pass
    return None


def _duration(artifact):
    value = str(artifact.get("Duration (ms)", ""))
    return int(value) if value.isdigit() and int(value) > 0 else None


def derive_statistics(artifacts, events):
    artifacts = [dict(item) for item in artifacts]
    museum_ids = {str(item.get("Museum ID", "")) for item in artifacts}
    uris = {f'spotify:track:{item.get("Source Track ID")}' for item in artifacts
            if item.get("Source Track ID")}
    durations = {str(item.get("Museum ID", "")): _duration(item) for item in artifacts}
    matching = [event for event in events if event.get("museum_id") in museum_ids or
                (event.get("spotify_uri") and event.get("spotify_uri") in uris)]
    matching.sort(key=lambda event: event["event_timestamp"])
    classifications = Counter(); total_ms = 0; known_durations = 0
    meaningful_plays = 0; completion_ratios = []
    years = Counter(); months = Counter(); hours = Counter()
    start_reasons = Counter(); end_reasons = Counter(); devices = Counter()
    operating_systems = Counter(); countries = Counter()
    shuffle = Counter(); offline = Counter()
    for event in matching:
        duration = durations.get(event.get("museum_id"))
        classification = classify_playback(event, duration)
        classifications[classification] += 1
        played = event.get("ms_played")
        if played is not None:
            total_ms += played; known_durations += 1
            if played >= 30000: meaningful_plays += 1
            if duration: completion_ratios.append(min(played / duration, 1.0))
        stamp = _parse_timestamp(event.get("event_timestamp"))
        if stamp:
            years[str(stamp.year)] += 1; months[stamp.strftime("%Y-%m")] += 1; hours[str(stamp.hour)] += 1
        if event.get("start_reason"): start_reasons[event["start_reason"]] += 1
        if event.get("end_reason"): end_reasons[event["end_reason"]] += 1
        if event.get("device_class"): devices[event["device_class"]] += 1
        if event.get("os"): operating_systems[event["os"]] += 1
        if event.get("country"): countries[event["country"]] += 1
        if event.get("shuffle") is not None: shuffle[str(event["shuffle"]).lower()] += 1
        if event.get("offline") is not None: offline[str(event["offline"]).lower()] += 1
    return {
        "artifacts": artifacts, "recorded_event_count": len(matching),
        "first_recorded_listen": matching[0]["event_timestamp"] if matching else "",
        "latest_recorded_listen": matching[-1]["event_timestamp"] if matching else "",
        "meaningful_plays": meaningful_plays,
        "completed_plays": classifications["completed_play"],
        "explicit_skips": classifications["explicit_skip"],
        "short_plays": classifications["short_play"],
        "interrupted_other": classifications["interrupted_or_other"],
        "total_listening_ms": total_ms if known_durations else None,
        "average_listening_ms": round(total_ms / known_durations) if known_durations else None,
        "average_completion": (sum(completion_ratios) / len(completion_ratios)) if completion_ratios else None,
        "activity_by_year": dict(sorted(years.items())), "activity_by_month": dict(sorted(months.items())),
        "activity_by_hour": dict(sorted(hours.items(), key=lambda item: int(item[0]))),
        "start_reasons": dict(start_reasons), "end_reasons": dict(end_reasons),
        "devices": dict(devices), "operating_systems": dict(operating_systems),
        "countries": dict(countries), "shuffle": dict(shuffle),
        "offline": dict(offline),
        "classifications": dict(classifications), "matching_events": matching,
    }


def inspect_artifact(artifact, events, manifest=None):
    result = derive_statistics([artifact], events); result["artifact"] = dict(artifact)
    occurrences = []
    if manifest is not None and not getattr(manifest, "empty", True):
        occurrences = manifest[manifest["Museum ID"].astype(str).eq(str(artifact.get("Museum ID", "")))].to_dict("records")
    result["playlist_occurrences"] = occurrences
    result["duplicate_occurrences"] = sum(row.get("Classification") == "duplicate occurrence" for row in occurrences)
    return result


def inspect_artist(collection, events, artist):
    rows = collection[collection["Artist"].map(normalize_search).eq(normalize_search(artist))]
    result = derive_statistics(rows.to_dict("records"), events); result["artist"] = artist
    per_track = defaultdict(lambda: {"events": 0, "listening_ms": 0})
    by_id = {row["Museum ID"]: row for row in rows.to_dict("records")}
    for event in result["matching_events"]:
        item = per_track[event.get("museum_id")]; item["events"] += 1; item["listening_ms"] += event.get("ms_played") or 0
    result["most_listened_tracks"] = sorted(
        ({"artifact": by_id[mid], **values} for mid, values in per_track.items() if mid in by_id),
        key=lambda item: (-item["events"], item["artifact"].get("Title", ""))
    )
    return result


def inspect_album(collection, events, album, artist=None):
    rows = collection[collection["Album"].map(normalize_search).eq(normalize_search(album))]
    if artist:
        rows = rows[rows["Artist"].map(normalize_search).eq(normalize_search(artist))]
    result = derive_statistics(rows.to_dict("records"), events)
    result.update({"album": album, "artist": artist or ""})
    per_track = defaultdict(lambda: {"events": 0, "listening_ms": 0})
    by_id = {row["Museum ID"]: row for row in rows.to_dict("records")}
    for event in result["matching_events"]:
        item = per_track[event.get("museum_id")]
        item["events"] += 1
        item["listening_ms"] += event.get("ms_played") or 0
    result["most_listened_tracks"] = sorted(
        ({"artifact": by_id[mid], **values} for mid, values in per_track.items() if mid in by_id),
        key=lambda item: (-item["events"], item["artifact"].get("Title", "")),
    )
    return result


def listening_overview(collection, events):
    return derive_statistics(collection.to_dict("records"), events)
