"""Synthetic tests for the central Museum Profile Engine."""

import os
import sys
import time
import unittest
from datetime import datetime

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

from profile_engine import (  # noqa: E402
    MIN_RATE_COMPARISON_SAMPLE, ProfileEngine, TIMEZONE_POLICY, coverage,
    format_count, format_date, format_datetime, format_duration,
    format_percentage, format_span, plural,
)
import exhibit_manager  # noqa: E402


def artifact(mid="MMT-000001", title="One", artist="Alpha feat. Guest", album="Shared", duration=100000):
    return {"Museum ID": mid, "Source Track ID": mid[-1], "Source": "Spotify",
            "Title": title, "Artist": artist, "Album": album,
            "Duration (ms)": str(duration), "Release Date": "2020-01-02",
            "Archived At": "2026-01-01T00:00:00Z", "Status": "available"}


def event(number, mid="MMT-000001", stamp=None, played=100000, **values):
    row = {"event_id": f"e{number}", "museum_id": mid,
           "spotify_uri": f"spotify:track:{mid[-1]}" if mid else "", "source_type": "technical_log",
           "event_timestamp": stamp or f"2026-01-{number:02}T0{number % 9}:00:00Z",
           "ms_played": played, "start_reason": "", "end_reason": "",
           "explicit_skip": None, "shuffle": None, "offline": None,
           "device_class": "", "os": "", "country": "", "match_status": "exact_uri",
           "match_method": "spotify_uri", "session_context": ""}
    row.update(values); return row


class FormattingTests(unittest.TestCase):
    def test_central_formatters_and_pluralization(self):
        self.assertEqual(format_count(22740), "22,740")
        self.assertEqual(format_date("2016-01-21T00:00:00Z"), "January 21, 2016")
        self.assertEqual(format_datetime("2026-02-08T21:58:00Z"), "February 8, 2026 at 9:58 PM")
        self.assertEqual(format_duration(15*3600000+35*60000), "15h 35m")
        self.assertEqual(format_percentage(.543), "54.3%")
        self.assertEqual(format_span(datetime(2025,1,1), datetime(2026,5,1)), "1 year, 4 months")
        self.assertEqual((plural(1,"event"), plural(2,"event")), ("event","events"))

    def test_coverage_distinguishes_zero_from_unavailable(self):
        unavailable = coverage("shuffle", 0, 10, [])
        observed = coverage("shuffle", 10, 10, ["rich"])
        self.assertFalse(unavailable["available"]); self.assertIsNone(unavailable["percentage"] if not unavailable["total_relevant_event_count"] else None)
        self.assertTrue(observed["available"]); self.assertEqual(observed["percentage"], 1)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.collection = pd.DataFrame([
            artifact(), artifact("MMT-000002", "Two", "Alpha", "Other", 200000),
            artifact("MMT-000003", "Three", "Beta", "Shared", 0),
            artifact("MMT-000004", "No Events", "Beta", "Shared", 100000),
        ])
        self.events = [
            event(1, stamp="2025-01-01T01:00:00Z", played=10000, explicit_skip=True,
                  end_reason="fwdbtn", start_reason="clickrow", shuffle=True, offline=False,
                  device_class="mobile", os="iOS", country="US"),
            event(2, stamp="2025-01-02T06:00:00Z", played=50000, end_reason="remote",
                  start_reason="trackdone", shuffle=False, offline=True, device_class="desktop", os="Windows", country="CA"),
            event(3, stamp="2025-02-15T13:00:00Z", played=100000, end_reason="trackdone",
                  start_reason="fwdbtn", shuffle=True, offline=False, device_class="mobile", os="Android", country="US"),
            event(4, stamp="2026-06-13T18:00:00Z", played=150000, end_reason="trackdone"),
            event(5, mid="MMT-000002", stamp="2026-06-14T22:00:00Z", played=200000, end_reason="endplay"),
            event(6, mid="", stamp="2026-06-15T22:00:00Z", played=30000,
                  match_status="unresolved", match_method="none"),
            event(7, mid="", stamp="2026-06-16T22:00:00Z", played=None,
                  match_status="ambiguous", match_method="normalized_title_artist"),
        ]
        manifest = pd.DataFrame([
            {"Museum ID":"MMT-000001","Playlist ID":"p1","Playlist Position":1,"Classification":"restorable","Added At":"2026-01-01"},
            {"Museum ID":"MMT-000001","Playlist ID":"p1","Playlist Position":2,"Classification":"duplicate occurrence","Added At":"2026-01-02"},
        ])
        exhibits = [{"exhibit_id":"EXH-1","display_number":3,"title":"Curated","type":"curated","artifact_ids":["MMT-000001"]}]
        self.engine = ProfileEngine(self.collection, self.events, manifest, exhibits, now=datetime(2026,8,9))

    def test_indexes_are_built_once_and_conservative(self):
        summary = self.engine.index_summary()
        self.assertEqual((summary["artifacts"], summary["events"], summary["artists"], summary["albums"]), (4,7,3,3))
        self.assertEqual(len(self.engine.events_by_artifact["MMT-000001"]), 4)
        self.assertNotIn("e6", {e["event_id"] for e in self.engine.events_by_artifact["MMT-000001"]})

    def test_artifact_classifications_rates_and_listening(self):
        p = self.engine.artifact_profile("MMT-000001")
        self.assertEqual((p["recorded_event_count"],p["meaningful_plays"],p["completed_plays"],p["natural_completions"],p["explicit_skips"]),(4,3,2,2,1))
        self.assertEqual(p["total_listening_ms"],310000)
        self.assertEqual(p["average_listening_ms"],77500)
        self.assertEqual(p["median_listening_ms"],75000)
        self.assertEqual(p["rates"]["explicit_skip"],.25)

    def test_completion_buckets_and_anomalies_are_capped(self):
        p=self.engine.artifact_profile("MMT-000001")["completion"]
        self.assertEqual(p["over_100_anomalies"],1);self.assertEqual(p["maximum"],1)
        self.assertEqual(p["distribution"]["100% / complete"],2)

    def test_history_active_units_gaps_and_streaks(self):
        p=self.engine.artifact_profile("MMT-000001")
        self.assertEqual(format_date(p["first_recorded_listen"]),"January 1, 2025")
        self.assertEqual(format_date(p["latest_recorded_listen"]),"June 13, 2026")
        self.assertEqual((p["active_days"],p["active_months"],p["active_years"]),(4,3,2))
        self.assertGreater(p["gaps"]["longest_seconds"],300*86400)
        self.assertEqual(p["streaks"]["daily"]["longest"],2)

    def test_peaks_hour_daypart_weekday_weekend(self):
        p=self.engine.artifact_profile("MMT-000001")
        self.assertEqual(p["peaks"]["year"]["by_events"],"2025")
        self.assertIn("Late Night",p["activity"]["daypart"])
        self.assertEqual(p["weekday_weekend"]["weekend_events"],2)

    def test_reasons_context_coverage_and_samples(self):
        p=self.engine.artifact_profile("MMT-000001")
        self.assertEqual(p["start_reasons"]["Direct selection"],1)
        self.assertEqual(p["end_reasons"]["Natural completion"],2)
        self.assertEqual(p["context"]["country"]["United States"]["events"],2)
        self.assertEqual(p["coverage"]["shuffle"]["eligible_event_count"],3)
        self.assertFalse(p["context"]["device"]["mobile"]["comparison_sample_adequate"])
        self.assertEqual(MIN_RATE_COMPARISON_SAMPLE,5)

    def test_rankings_shares_milestones_preservation_and_exhibits(self):
        p=self.engine.artifact_profile("MMT-000001")
        self.assertEqual(p["rankings"]["recorded_events"]["rank"],1)
        self.assertEqual(p["shares"]["resolved_events"],4/5)
        self.assertEqual((p["playlist_count"],len(p["playlist_occurrences"]),p["duplicate_occurrences"]),(1,2,1))
        self.assertEqual(p["exhibits"][0]["title"],"Curated")
        self.assertEqual(p["milestones"][0]["value"],1)

    def test_zero_event_unknown_and_zero_duration(self):
        p=self.engine.artifact_profile("MMT-000004")
        self.assertEqual(p["recorded_event_count"],0);self.assertIsNone(p["total_listening_ms"])
        zero=self.engine.artifact_profile("MMT-000003")
        self.assertFalse(zero["completion"]["distribution"])

    def test_artist_collaboration_and_aggregation(self):
        alpha=self.engine.artist_profile("Alpha");guest=self.engine.artist_profile("Guest")
        self.assertEqual(alpha["recorded_event_count"],5)
        self.assertEqual(guest["recorded_event_count"],4)
        self.assertIn("Each credited artist",alpha["collaboration_attribution"])
        self.assertEqual(alpha["top_tracks"][0]["museum_id"],"MMT-000001")

    def test_album_identity_and_profiles(self):
        with self.assertRaises(KeyError): self.engine.album_profile("Shared")
        p=self.engine.album_profile("Shared","Alpha feat. Guest")
        self.assertEqual(p["preserved_track_count"],1);self.assertEqual(p["tracks_with_events"],1)
        beta=self.engine.album_profile("Shared","Beta")
        self.assertEqual(beta["recorded_event_count"],0)

    def test_museum_totals_and_coverage(self):
        p=self.engine.museum_profile()
        self.assertEqual((p["total_recorded_events"],p["resolved_events"],p["unresolved_events"],p["ambiguous_events"]),(7,5,1,1))
        self.assertEqual((p["distinct_tracks"],p["distinct_artists"],p["distinct_albums"]),(2,2,2))
        self.assertTrue(p["top_tracks"])

    def test_quick_story_is_deterministic_and_non_emotional(self):
        p=self.engine.artifact_profile("MMT-000001")
        self.assertEqual(p["quick_story"],self.engine.quick_story(p))
        story=" ".join(p["quick_story"]).casefold()
        for word in ("favorite","loved","obsessed","nostalgic","rediscovered"):
            self.assertNotIn(word,story)

    def test_timezone_and_session_limitations_are_explicit(self):
        self.assertEqual(self.engine.artifact_profile("MMT-000001")["timezone_policy"],TIMEZONE_POLICY)
        decision=self.engine.session_analysis();self.assertFalse(decision["implemented"])
        self.assertIn("unsupported behavioral assumption",decision["reason"])

    def test_automatic_exhibit_and_profile_rankings_agree_and_story_uses_metric(self):
        index=exhibit_manager.build_exhibit_index(self.collection,self.events)
        exhibit=exhibit_manager.create_exhibit("Time","automatic",rule={"metric":"most_listening_time"})
        result=exhibit_manager.evaluate_automatic_exhibit(exhibit,index)
        top_profile=self.engine.museum_profile()["top_tracks"]
        top_profile=sorted(top_profile,key=lambda r:(-(r["total_listening_ms"] or 0),r["display"].casefold(),r["id"]))[0]
        self.assertEqual(result["rows"][0]["entity_id"],top_profile["id"])
        self.assertIn("recorded listening",result["story"][1])
        self.assertNotIn("highest-ranked result",result["story"][1])


class PerformanceTests(unittest.TestCase):
    def test_100k_event_profile_build_has_linear_index_shape(self):
        collection=pd.DataFrame([artifact(f"MMT-{i:06}",f"Track {i}",f"Artist {i%20}",f"Album {i%100}") for i in range(1,101)])
        events=[event(i,mid=f"MMT-{(i%100)+1:06}",stamp=f"2026-{(i%12)+1:02}-{(i%28)+1:02}T{i%24:02}:00:00Z",played=30000) for i in range(1,100001)]
        started=time.perf_counter();engine=ProfileEngine(collection,events);profile=engine.artifact_profile("MMT-000001");elapsed=time.perf_counter()-started
        self.assertEqual((engine.index_summary()["events"],profile["recorded_event_count"]),(100000,1000))
        self.assertLess(elapsed,30, f"Representative 100k-event construction took {elapsed:.3f}s")


if __name__ == "__main__": unittest.main()
