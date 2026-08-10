"""Session-scoped Museum statistics, profiles, rankings, and stories.

Recorded values remain available in ``raw`` fields.  Everything else in a
profile is a deterministic calculation over the normalized Collection,
Listening Archive, manifests, and Exhibits supplied to the engine.
"""

import calendar
import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from listening_archive import classify_playback


MEANINGFUL_MS = 30_000
MIN_RATE_COMPARISON_SAMPLE = 5
MIN_STREAK_EVENTS = 2
TIMEZONE_POLICY = (
    "Time-of-day statistics use recorded timestamps (including UTC where supplied); "
    "original local timezone is not available for every event."
)
DAYPARTS = (
    ("Late Night", 0, 5), ("Morning", 5, 12), ("Afternoon", 12, 17),
    ("Evening", 17, 21), ("Night", 21, 24),
)
START_REASON_LABELS = {
    "clickrow": "Direct selection", "clicked track": "Direct selection",
    "direct selection": "Direct selection", "playbtn": "Play action",
    "play button": "Play action", "fwdbtn": "Forward action",
    "forward button": "Forward action", "backbtn": "Back action",
    "back button": "Back action", "trackdone": "Previous track completed",
    "track done": "Previous track completed", "appload": "App/start context",
    "app load": "App/start context", "remote": "Remote playback action",
}
END_REASON_LABELS = {
    "trackdone": "Natural completion", "track done": "Natural completion",
    "track completed": "Natural completion", "endplay": "Natural completion",
    "fwdbtn": "Forward action", "forward button": "Forward action",
    "backbtn": "Back action", "back button": "Back action",
    "end play": "End play", "track error": "Track error",
    "remote": "Remote action", "remote action": "Remote action",
}
COUNTRIES = {
    "US": "United States", "CA": "Canada", "GB": "United Kingdom",
    "AU": "Australia", "DE": "Germany", "FR": "France", "MX": "Mexico",
    "JP": "Japan", "BR": "Brazil", "ES": "Spain", "IT": "Italy",
}
EVENT_MILESTONES = (1, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
TIME_MILESTONES_HOURS = (1, 5, 10, 24, 50, 100, 250, 500)


def normalize_identity(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def format_count(value):
    return f"{int(value or 0):,}"


def parse_timestamp(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def format_date(value):
    parsed = value if isinstance(value, (date, datetime)) else parse_timestamp(value)
    return parsed.strftime("%B %d, %Y").replace(" 0", " ") if parsed else "Unavailable"


def format_datetime(value):
    parsed = value if isinstance(value, datetime) else parse_timestamp(value)
    if not parsed:
        return "Unavailable"
    hour = parsed.strftime("%I").lstrip("0") or "12"
    return f"{parsed.strftime('%B %d, %Y').replace(' 0', ' ')} at {hour}:{parsed:%M %p}"


def format_duration(milliseconds):
    if milliseconds is None:
        return "Unavailable"
    seconds = max(0, int(milliseconds) // 1000)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {seconds}s"


def format_percentage(value, precision=None):
    if value is None:
        return "Unavailable"
    percent = float(value) * 100
    if precision is None:
        precision = 1 if not math.isclose(percent, round(percent), abs_tol=.05) else 0
    return f"{percent:.{precision}f}%"


def _whole_months(start, end):
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(0, months)


def format_span(start=None, end=None, days=None):
    if days is not None:
        start = datetime(2000, 1, 1); end = start.fromordinal(start.toordinal() + int(days))
    if not start or not end:
        return "Unavailable"
    months = _whole_months(start, end)
    anchor_days = min(28, start.day)
    anchor = datetime(start.year + (start.month - 1 + months) // 12,
                      (start.month - 1 + months) % 12 + 1, anchor_days)
    remaining = max(0, (end.date() - anchor.date()).days)
    years, months = divmod(months, 12)
    parts = []
    if years: parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months: parts.append(f"{months} month{'s' if months != 1 else ''}")
    if remaining or not parts: parts.append(f"{remaining} day{'s' if remaining != 1 else ''}")
    return ", ".join(parts)


def plural(count, singular, plural_word=None):
    return singular if count == 1 else (plural_word or singular + "s")


def coverage(field, eligible, total, sources=()):
    return {
        "field": field, "eligible_event_count": int(eligible),
        "total_relevant_event_count": int(total),
        "percentage": (eligible / total) if total else None,
        "source_types": sorted(set(sources)), "available": bool(eligible),
    }


def _integer(value):
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _artist_credits(value):
    # Collection artist strings have no lossless collaboration delimiter.
    # Semicolon and explicit " feat. "/" featuring " are treated as credits;
    # commas are preserved because they can be part of an artist name.
    text = str(value or "").strip()
    parts = re.split(r"\s*;\s*|\s+(?:feat\.?|featuring)\s+", text, flags=re.I)
    return [part.strip() for part in parts if part.strip()] or ([text] if text else [])


def _album_key(artifact):
    return (normalize_identity(artifact.get("Artist")), normalize_identity(artifact.get("Album")))


def _daypart(hour):
    return next(label for label, start, end in DAYPARTS if start <= hour < end)


def _streak(values):
    ordered = sorted(set(values))
    if not ordered:
        return {"longest": 0, "current": 0, "longest_values": []}
    groups = [[ordered[0]]]
    for item in ordered[1:]:
        if item - groups[-1][-1] == 1: groups[-1].append(item)
        else: groups.append([item])
    longest_length = max(map(len, groups))
    longest = min((group for group in groups if len(group) == longest_length), key=lambda g: g[0])
    return {"longest": len(longest), "current": len(groups[-1]), "longest_values": longest}


class ProfileEngine:
    """Immutable-input, disposable in-memory indexes and structured profiles."""

    def __init__(self, collection, events, manifest=None, exhibits=None, now=None):
        self.artifacts = self._records(collection)
        self.events = list(events or [])
        self.manifest = self._records(manifest)
        self.exhibits = list(exhibits or [])
        self.now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
        self._profiles = {}
        self._build_indexes()

    @staticmethod
    def _records(value):
        if value is None: return []
        if hasattr(value, "to_dict"): return value.to_dict(orient="records")
        return [dict(item) for item in value]

    def _build_indexes(self):
        self.artifact_by_id = {}
        self.artifact_by_uri = {}
        self.artifact_by_track_id = {}
        self.artist_artifacts = defaultdict(set)
        self.album_artifacts = defaultdict(set)
        for artifact in self.artifacts:
            mid = str(artifact.get("Museum ID", ""))
            if not mid: continue
            self.artifact_by_id[mid] = artifact
            track_id = str(artifact.get("Source Track ID", "") or "").strip()
            if track_id:
                self.artifact_by_track_id[track_id] = artifact
                self.artifact_by_uri[f"spotify:track:{track_id}"] = artifact
            for artist in _artist_credits(artifact.get("Artist")):
                self.artist_artifacts[normalize_identity(artist)].add(mid)
            self.album_artifacts[_album_key(artifact)].add(mid)
        self.event_by_id = {}
        self.events_by_artifact = defaultdict(list)
        self.events_by_artist = defaultdict(list)
        self.events_by_album = defaultdict(list)
        self.events_by_year = defaultdict(list); self.events_by_month = defaultdict(list)
        self.events_by_day = defaultdict(list)
        for event in self.events:
            event_id = str(event.get("event_id", ""))
            if event_id: self.event_by_id[event_id] = event
            mid = str(event.get("museum_id", "") or "")
            artifact = self.artifact_by_id.get(mid) or self.artifact_by_uri.get(event.get("spotify_uri"))
            if artifact:
                mid = str(artifact.get("Museum ID")); self.events_by_artifact[mid].append(event)
                for artist in _artist_credits(artifact.get("Artist")):
                    self.events_by_artist[normalize_identity(artist)].append(event)
                self.events_by_album[_album_key(artifact)].append(event)
            stamp = parse_timestamp(event.get("event_timestamp"))
            if stamp:
                self.events_by_year[str(stamp.year)].append(event)
                self.events_by_month[stamp.strftime("%Y-%m")].append(event)
                self.events_by_day[stamp.date().isoformat()].append(event)
        for mapping in (self.events_by_artifact, self.events_by_artist, self.events_by_album,
                        self.events_by_year, self.events_by_month, self.events_by_day):
            for key in mapping: mapping[key].sort(key=self._event_sort)
        self.playlist_occurrences = defaultdict(list); self.playlist_ids = defaultdict(set)
        for row in self.manifest:
            mid = str(row.get("Museum ID", ""))
            if mid:
                self.playlist_occurrences[mid].append(row)
                playlist = str(row.get("Playlist ID") or row.get("Playlist Name") or row.get("Source Playlist") or "")
                if playlist: self.playlist_ids[mid].add(playlist)
        self.exhibit_membership = defaultdict(list)
        for exhibit in self.exhibits:
            for mid in exhibit.get("artifact_ids", []):
                self.exhibit_membership[str(mid)].append({
                    "exhibit_id": exhibit.get("exhibit_id"), "display_number": exhibit.get("display_number"),
                    "title": exhibit.get("title", ""), "type": exhibit.get("type", ""),
                })

    @staticmethod
    def _event_sort(event):
        return (parse_timestamp(event.get("event_timestamp")) or datetime.min, str(event.get("event_id", "")))

    def index_summary(self):
        return {"artifacts": len(self.artifact_by_id), "events": len(self.events),
                "event_ids": len(self.event_by_id), "artists": len(self.artist_artifacts),
                "albums": len(self.album_artifacts), "years": len(self.events_by_year),
                "months": len(self.events_by_month), "days": len(self.events_by_day)}

    def _aggregate(self, artifacts, events):
        artifacts = list(artifacts); events = sorted(events, key=self._event_sort)
        durations = {str(a.get("Museum ID")): _integer(a.get("Duration (ms)")) for a in artifacts}
        classes = Counter(); natural = 0; meaningful_count = 0; played_values = []; ratios = []; meaningful_ratios = []
        completion_buckets = Counter(); anomalies = 0
        stamps = []; by_day = defaultdict(lambda: [0, 0]); by_week = defaultdict(lambda: [0, 0])
        by_month = defaultdict(lambda: [0, 0]); by_year = defaultdict(lambda: [0, 0])
        by_hour = defaultdict(lambda: [0, 0]); by_daypart = defaultdict(lambda: [0, 0])
        by_weekday = defaultdict(lambda: [0, 0])
        starts = Counter(); ends = Counter(); contexts = {name: defaultdict(list) for name in
            ("shuffle", "offline", "device", "os", "country")}
        field_sources = defaultdict(set); field_counts = Counter()
        first_meaningful = latest_meaningful = first_completion = latest_completion = None
        for event in events:
            mid = str(event.get("museum_id", "")); duration = durations.get(mid)
            played = _integer(event.get("ms_played")); classification = classify_playback(event, duration)
            classes[classification] += 1
            stamp = parse_timestamp(event.get("event_timestamp"))
            if stamp: stamps.append(stamp)
            if played is not None:
                played_values.append(played); field_counts["ms_played"] += 1
                if played >= MEANINGFUL_MS: meaningful_count += 1
                field_sources["ms_played"].add(event.get("source_type", ""))
                if duration:
                    raw_ratio = played / duration
                    if raw_ratio > 1: anomalies += 1
                    ratio = min(raw_ratio, 1.0); ratios.append(ratio)
                    if played >= MEANINGFUL_MS: meaningful_ratios.append(ratio)
                    bucket = ("100% / complete" if raw_ratio >= 1 else "90-99%" if ratio >= .9 else
                              "75-89%" if ratio >= .75 else "50-74%" if ratio >= .5 else
                              "25-49%" if ratio >= .25 else "0-24%")
                    completion_buckets[bucket] += 1
            if classification in {"meaningful_play", "completed_play"} and stamp:
                first_meaningful = first_meaningful or stamp; latest_meaningful = stamp
            if classification == "completed_play" and stamp:
                first_completion = first_completion or stamp; latest_completion = stamp
            end_raw = str(event.get("end_reason", "") or "").strip().casefold()
            if end_raw in {"trackdone", "track done", "track completed", "endplay"}: natural += 1
            if stamp:
                iso = stamp.isocalendar(); week = f"{iso.year}-W{iso.week:02}"
                keys = ((by_day, stamp.date().isoformat()), (by_week, week),
                        (by_month, stamp.strftime("%Y-%m")), (by_year, str(stamp.year)),
                        (by_hour, stamp.hour), (by_daypart, _daypart(stamp.hour)),
                        (by_weekday, calendar.day_name[stamp.weekday()]))
                for mapping, key in keys:
                    mapping[key][0] += 1; mapping[key][1] += played or 0
            start_raw = str(event.get("start_reason", "") or "").strip()
            if start_raw:
                starts[START_REASON_LABELS.get(start_raw.casefold(), "Other")] += 1
                field_counts["start_reason"] += 1; field_sources["start_reason"].add(event.get("source_type", ""))
            if end_raw:
                ends[END_REASON_LABELS.get(end_raw, "Other")] += 1
                field_counts["end_reason"] += 1; field_sources["end_reason"].add(event.get("source_type", ""))
            context_values = {
                "shuffle": event.get("shuffle"), "offline": event.get("offline"),
                "device": str(event.get("device_class", "") or "").strip(),
                "os": str(event.get("os", "") or "").strip(),
                "country": str(event.get("country", "") or "").strip().upper(),
            }
            for field, value in context_values.items():
                if value is None or value == "": continue
                if field == "country": value = COUNTRIES.get(value, value)
                contexts[field][value].append((classification, played))
                field_counts[field] += 1; field_sources[field].add(event.get("source_type", ""))
        def rate(numerator, denominator): return numerator / denominator if denominator else None
        event_count = len(events); completed = classes["completed_play"]
        active_dates = [datetime.fromisoformat(key).date().toordinal() for key in by_day]
        active_weeks = []
        for key in by_week:
            year, week = key.split("-W"); active_weeks.append(date.fromisocalendar(int(year), int(week), 1).toordinal() // 7)
        daily = _streak(active_dates); weekly = _streak(active_weeks)
        gaps = [(right - left).total_seconds() for left, right in zip(stamps, stamps[1:])]
        positive_gaps = [gap for gap in gaps if gap >= 0]
        meaningful_stamps = [parse_timestamp(e.get("event_timestamp")) for e in events
                             if classify_playback(e, durations.get(str(e.get("museum_id", "")))) in {"meaningful_play", "completed_play"}]
        meaningful_stamps = [stamp for stamp in meaningful_stamps if stamp]
        meaningful_gaps = [(b-a).total_seconds() for a, b in zip(meaningful_stamps, meaningful_stamps[1:]) if b >= a]
        peak = lambda mapping, pos: min(mapping, key=lambda key: (-mapping[key][pos], str(key))) if mapping else None
        context_stats = {}
        for field, groups in contexts.items():
            context_stats[field] = {}
            for value, rows in sorted(groups.items(), key=lambda item: str(item[0])):
                eligible = len(rows); known = [ms for _, ms in rows if ms is not None]
                complete_count = sum(kind == "completed_play" for kind, _ in rows)
                skip_count = sum(kind == "explicit_skip" for kind, _ in rows)
                context_stats[field][str(value)] = {
                    "events": eligible, "listening_ms": sum(known),
                    "completion_rate": rate(complete_count, eligible), "explicit_skip_rate": rate(skip_count, eligible),
                    "average_listening_ms": round(statistics.mean(known)) if known else None,
                    "comparison_sample_adequate": eligible >= MIN_RATE_COMPARISON_SAMPLE,
                }
        coverages = {field: coverage(field, field_counts[field], event_count, field_sources[field])
                     for field in ("ms_played", "start_reason", "end_reason", "shuffle", "offline", "device", "os", "country")}
        return {
            "recorded_event_count": event_count, "meaningful_plays": meaningful_count,
            "completed_plays": completed, "natural_completions": natural,
            "explicit_skips": classes["explicit_skip"], "short_plays": classes["short_play"],
            "interrupted_other": classes["interrupted_or_other"], "classifications": dict(classes),
            "rates": {"meaningful_play": rate(meaningful_count, event_count),
                      "completion": rate(completed, event_count), "natural_completion": rate(natural, field_counts["end_reason"]),
                      "explicit_skip": rate(classes["explicit_skip"], event_count), "short_play": rate(classes["short_play"], event_count)},
            "total_listening_ms": sum(played_values) if played_values else None,
            "average_listening_ms": round(statistics.mean(played_values)) if played_values else None,
            "median_listening_ms": round(statistics.median(played_values)) if played_values else None,
            "minimum_listening_ms": min(played_values) if played_values else None,
            "maximum_listening_ms": max(played_values) if played_values else None,
            "completion": {"average": statistics.mean(ratios) if ratios else None,
                           "median": statistics.median(ratios) if ratios else None,
                           "minimum_meaningful": min(meaningful_ratios) if meaningful_ratios else None,
                           "maximum": max(ratios) if ratios else None, "distribution": dict(completion_buckets),
                           "over_100_anomalies": anomalies, "display_ratios_capped": True},
            "first_recorded_listen": stamps[0] if stamps else None, "latest_recorded_listen": stamps[-1] if stamps else None,
            "relationship_span": (stamps[-1] - stamps[0]) if len(stamps) > 1 else None,
            "days_since_latest": (self.now.date() - stamps[-1].date()).days if stamps else None,
            "first_meaningful_play": first_meaningful, "latest_meaningful_play": latest_meaningful,
            "first_recorded_completion": first_completion, "latest_recorded_completion": latest_completion,
            "active_days": len(by_day), "active_weeks": len(by_week), "active_months": len(by_month), "active_years": len(by_year),
            "average_events_per_active_day": rate(event_count, len(by_day)),
            "average_listening_ms_per_active_day": rate(sum(played_values), len(by_day)) if played_values else None,
            "gaps": {"longest_seconds": max(positive_gaps) if positive_gaps else None,
                     "median_seconds": statistics.median(positive_gaps) if positive_gaps else None,
                     "average_seconds": statistics.mean(positive_gaps) if positive_gaps else None,
                     "shortest_meaningful_seconds": min(meaningful_gaps) if meaningful_gaps else None},
            "streaks": {"daily": daily, "weekly": weekly,
                        "display_adequate": event_count >= MIN_STREAK_EVENTS},
            "activity": {"day": dict(by_day), "week": dict(by_week), "month": dict(by_month), "year": dict(by_year),
                         "hour": dict(by_hour), "daypart": dict(by_daypart), "weekday": dict(by_weekday)},
            "peaks": {unit: {"by_events": peak(mapping, 0), "by_listening_time": peak(mapping, 1)}
                      for unit, mapping in (("day", by_day), ("week", by_week), ("month", by_month), ("year", by_year),
                                            ("hour", by_hour), ("daypart", by_daypart))},
            "weekday_weekend": {"weekday_events": sum(v[0] for k,v in by_weekday.items() if k not in {"Saturday","Sunday"}),
                                "weekend_events": sum(v[0] for k,v in by_weekday.items() if k in {"Saturday","Sunday"}),
                                "weekday_listening_ms": sum(v[1] for k,v in by_weekday.items() if k not in {"Saturday","Sunday"}),
                                "weekend_listening_ms": sum(v[1] for k,v in by_weekday.items() if k in {"Saturday","Sunday"})},
            "start_reasons": dict(starts), "end_reasons": dict(ends), "context": context_stats,
            "coverage": coverages, "timezone_policy": TIMEZONE_POLICY, "matching_events": events,
        }

    def _rankings(self, entity_type, identity, stats, scopes=None):
        scopes = scopes or {}
        result = {}
        metrics = {"recorded_events": "recorded_event_count", "listening_time": "total_listening_ms",
                   "meaningful_plays": "meaningful_plays", "completed_plays": "completed_plays",
                   "natural_completions": "natural_completions", "explicit_skips": "explicit_skips"}
        candidates = scopes.get("all") or self._all_entity_summaries(entity_type)
        for label, field in metrics.items():
            ranked = sorted(candidates, key=lambda row: (-(row.get(field) or 0), normalize_identity(row.get("display")), row.get("id", "")))
            position = next((i for i, row in enumerate(ranked, 1) if row["id"] == identity), None)
            result[label] = {"rank": position, "of": len(ranked), "value": stats.get(field),
                             "tie_policy": "metric descending, normalized display identity, stable identity"}
        return result

    def _all_entity_summaries(self, entity_type):
        cache_key = ("summaries", entity_type)
        if cache_key in self._profiles: return self._profiles[cache_key]
        rows = []
        if entity_type == "artifact":
            subjects = ((mid, a.get("Title", ""), [a], self.events_by_artifact.get(mid, [])) for mid,a in self.artifact_by_id.items())
        elif entity_type == "artist":
            subjects = ((key, next((a for a in _artist_credits(self.artifact_by_id[next(iter(mids))].get("Artist")) if normalize_identity(a)==key), key),
                         [self.artifact_by_id[mid] for mid in mids], self.events_by_artist.get(key, [])) for key,mids in self.artist_artifacts.items())
        else:
            subjects = (("\x1f".join(key), self.artifact_by_id[next(iter(mids))].get("Album", ""),
                         [self.artifact_by_id[mid] for mid in mids], self.events_by_album.get(key, [])) for key,mids in self.album_artifacts.items())
        for identity, display, artifacts, events in subjects:
            stat = self._aggregate(artifacts, events)
            rows.append({"id": identity, "display": display, **{key: stat.get(key) for key in
                ("recorded_event_count","total_listening_ms","meaningful_plays","completed_plays","natural_completions","explicit_skips")}})
        self._profiles[cache_key] = rows
        return rows

    def _milestones(self, events):
        ordered = sorted(events, key=self._event_sort); result = []; cumulative = 0; reached_hours = set()
        for number, event in enumerate(ordered, 1):
            stamp = parse_timestamp(event.get("event_timestamp")); cumulative += _integer(event.get("ms_played")) or 0
            if number in EVENT_MILESTONES:
                result.append({"type": "events", "value": number, "reached_at": stamp})
            for hours in TIME_MILESTONES_HOURS:
                if hours not in reached_hours and cumulative >= hours * 3_600_000:
                    reached_hours.add(hours); result.append({"type": "listening_time", "value": hours * 3_600_000, "reached_at": stamp})
        return sorted(result, key=lambda item: (item["reached_at"] or datetime.max, item["type"], item["value"]))

    def artifact_profile(self, museum_id):
        key = ("artifact", str(museum_id))
        if key in self._profiles: return self._profiles[key]
        artifact = self.artifact_by_id[str(museum_id)]; events = self.events_by_artifact.get(str(museum_id), [])
        stats = self._aggregate([artifact], events); occurrences = self.playlist_occurrences.get(str(museum_id), [])
        profile = {"profile_type": "artifact", "identity": dict(artifact), **stats,
                   "playlist_occurrences": list(occurrences), "playlist_count": len(self.playlist_ids.get(str(museum_id), set())),
                   "duplicate_occurrences": sum(str(row.get("Classification", "")).casefold()=="duplicate occurrence" for row in occurrences),
                   "exhibits": sorted(self.exhibit_membership.get(str(museum_id), []), key=lambda x: (x.get("display_number") or 0, x["title"])),
                   "milestones": self._milestones(events)}
        profile["rankings"] = self._rankings("artifact", str(museum_id), profile)
        total_resolved = sum(len(rows) for rows in self.events_by_artifact.values())
        total_ms = sum((_integer(e.get("ms_played")) or 0) for rows in self.events_by_artifact.values() for e in rows)
        profile["shares"] = {"resolved_events": profile["recorded_event_count"] / total_resolved if total_resolved else None,
                             "resolved_listening_time": (profile["total_listening_ms"] or 0) / total_ms if total_ms else None}
        artist_keys = [normalize_identity(a) for a in _artist_credits(artifact.get("Artist"))]
        if artist_keys:
            artist_events = self.events_by_artist.get(artist_keys[0], []); artist_ms = sum((_integer(e.get("ms_played")) or 0) for e in artist_events)
            profile["shares"]["primary_artist_events"] = len(events)/len(artist_events) if artist_events else None
            profile["shares"]["primary_artist_listening_time"] = (profile["total_listening_ms"] or 0)/artist_ms if artist_ms else None
        album_events = self.events_by_album.get(_album_key(artifact), []); album_ms = sum((_integer(e.get("ms_played")) or 0) for e in album_events)
        profile["shares"]["album_events"] = len(events)/len(album_events) if album_events else None
        profile["shares"]["album_listening_time"] = (profile["total_listening_ms"] or 0)/album_ms if album_ms else None
        profile["quick_story"] = self.quick_story(profile)
        self._profiles[key] = profile; return profile

    def artist_profile(self, artist):
        identity = normalize_identity(artist); key = ("artist", identity)
        if key in self._profiles: return self._profiles[key]
        mids = sorted(self.artist_artifacts.get(identity, set())); artifacts = [self.artifact_by_id[mid] for mid in mids]
        stats = self._aggregate(artifacts, self.events_by_artist.get(identity, []))
        tracks = [self._track_summary(mid) for mid in mids]
        albums = defaultdict(lambda: {"events":0,"listening_ms":0,"tracks":set()})
        for mid in mids:
            artifact = self.artifact_by_id[mid]; label = artifact.get("Album", "")
            albums[label]["tracks"].add(mid)
            for event in self.events_by_artifact.get(mid, []): albums[label]["events"] += 1; albums[label]["listening_ms"] += _integer(event.get("ms_played")) or 0
        profile = {"profile_type":"artist", "artist":artist, "identity":identity, "artifacts":artifacts, **stats,
                   "album_count":len({_album_key(a) for a in artifacts}),
                   "top_tracks":sorted(tracks,key=lambda r:(-r["recorded_event_count"],normalize_identity(r["title"]),r["museum_id"])),
                   "top_albums":sorted(({"album":k,**v,"track_count":len(v["tracks"])} for k,v in albums.items()),key=lambda r:(-r["events"],normalize_identity(r["album"]))),
                   "collaboration_attribution":"Each credited artist receives the event; Museum-wide totals remain event-based and are not summed from artist profiles."}
        profile["rankings"] = self._rankings("artist", identity, profile)
        total_resolved = sum(len(v) for v in self.events_by_artifact.values()); total_ms = sum((_integer(e.get("ms_played")) or 0) for v in self.events_by_artifact.values() for e in v)
        profile["shares"]={"resolved_events":len(profile["matching_events"])/total_resolved if total_resolved else None,
                           "resolved_listening_time": (profile["total_listening_ms"] or 0)/total_ms if total_ms else None}
        profile["milestones"]=self._milestones(profile["matching_events"]); profile["quick_story"]=self.quick_story(profile)
        self._profiles[key]=profile; return profile

    def album_profile(self, album, artist=None):
        candidates=[key for key in self.album_artifacts if key[1]==normalize_identity(album) and (not artist or key[0]==normalize_identity(artist))]
        if len(candidates)!=1: raise KeyError("Album identity is missing or ambiguous; artist + album is required.")
        album_key=candidates[0]; cache=("album",album_key)
        if cache in self._profiles:return self._profiles[cache]
        mids=sorted(self.album_artifacts[album_key]); artifacts=[self.artifact_by_id[mid] for mid in mids]
        stats=self._aggregate(artifacts,self.events_by_album.get(album_key,[])); tracks=[self._track_summary(mid) for mid in mids]
        represented=sum(bool(self.events_by_artifact.get(mid)) for mid in mids)
        profile={"profile_type":"album","album":album,"artist":artist or artifacts[0].get("Artist",""),"identity":"\x1f".join(album_key),
                 "artifacts":artifacts,**stats,"preserved_track_count":len(mids),"tracks_with_events":represented,
                 "archive_representation":represented/len(mids) if mids else None,
                 "top_tracks":sorted(tracks,key=lambda r:(-r["recorded_event_count"],normalize_identity(r["title"]),r["museum_id"]))}
        profile["rankings"]=self._rankings("album",profile["identity"],profile)
        profile["milestones"]=self._milestones(profile["matching_events"]);profile["quick_story"]=self.quick_story(profile)
        self._profiles[cache]=profile;return profile

    def _track_summary(self, mid):
        artifact=self.artifact_by_id[mid]; events=self.events_by_artifact.get(mid,[]); stats=self._aggregate([artifact],events)
        return {"museum_id":mid,"title":artifact.get("Title",""),"artist":artifact.get("Artist",""),"album":artifact.get("Album",""),
                **{k:stats[k] for k in ("recorded_event_count","total_listening_ms","meaningful_plays","completed_plays")}}

    def museum_profile(self):
        key=("museum","all")
        if key in self._profiles:return self._profiles[key]
        resolved=[e for e in self.events if str(e.get("museum_id", "")) in self.artifact_by_id]
        stats=self._aggregate(self.artifacts,resolved);statuses=Counter(str(e.get("match_status") or "unresolved") for e in self.events)
        profile={"profile_type":"museum","identity":"museum","artifacts":self.artifacts,**stats,
                 "total_recorded_events":len(self.events),"resolved_events":len(resolved),
                 "unresolved_events":statuses["unresolved"],"ambiguous_events":statuses["ambiguous"],
                 "rich_playback_events":sum(str(e.get("source_type","")).casefold()!="spotify_account_data" for e in self.events),
                 "title_artist_only_events":sum(e.get("match_method")=="normalized_title_artist" for e in self.events),
                 "distinct_tracks":len({e.get("museum_id") for e in resolved}),
                 "distinct_artists":len({normalize_identity(a) for e in resolved for a in _artist_credits(self.artifact_by_id[e["museum_id"]].get("Artist"))}),
                 "distinct_albums":len({_album_key(self.artifact_by_id[e["museum_id"]]) for e in resolved})}
        profile["top_tracks"]=self._all_entity_summaries("artifact");profile["top_artists"]=self._all_entity_summaries("artist");profile["top_albums"]=self._all_entity_summaries("album")
        for field in ("top_tracks","top_artists","top_albums"):
            profile[field]=sorted(profile[field],key=lambda r:(-(r.get("recorded_event_count") or 0),normalize_identity(r["display"]),r["id"]))
        profile["milestones"]=self._milestones(resolved);profile["quick_story"]=self.quick_story(profile)
        self._profiles[key]=profile;return profile

    def quick_story(self, profile):
        count=profile.get("recorded_event_count",0); subject={"artifact":"this artifact","artist":"this artist","album":"this album","museum":"the resolved archive"}.get(profile.get("profile_type"),"this subject")
        sentences=[]
        if count:
            time_text=format_duration(profile.get("total_listening_ms")) if profile.get("total_listening_ms") is not None else None
            sentence=f"There {'is' if count==1 else 'are'} {format_count(count)} recorded listening {plural(count,'event')} for {subject}"
            if time_text:sentence+=f", representing {time_text} of recorded listening"
            sentences.append(sentence+".")
        first=profile.get("first_recorded_listen");latest=profile.get("latest_recorded_listen")
        if first and latest and first!=latest:
            sentences.append(f"Recorded history runs from {format_date(first)} to {format_date(latest)}, a span of {format_span(first,latest)}.")
        peak=profile.get("peaks",{}).get("year",{}).get("by_events")
        if peak:sentences.append(f"Recorded activity was highest during {peak}.")
        daypart=profile.get("peaks",{}).get("daypart",{}).get("by_events")
        if daypart and profile.get("activity",{}).get("daypart",{}).get(daypart,[0])[0]>=MIN_RATE_COMPARISON_SAMPLE:
            sentences.append(f"The largest timestamped event count falls in the Museum's {daypart.lower()} period.")
        rank=profile.get("rankings",{}).get("recorded_events")
        if rank and rank.get("rank"):
            sentences.append(f"It ranks #{rank['rank']} by recorded events among {format_count(rank['of'])} resolved {plural(rank['of'],profile.get('profile_type','subject'))}.")
        return sentences

    def session_analysis(self):
        populated=sum(bool(str(e.get("session_context","")).strip()) for e in self.events)
        return {"implemented":False,"source_session_coverage":coverage("session_context",populated,len(self.events),
                [e.get("source_type","") for e in self.events if e.get("session_context")]),
                "reason":"Normalized session_context is not documented as a stable session identity; gap-derived sessions would add an unsupported behavioral assumption."}
