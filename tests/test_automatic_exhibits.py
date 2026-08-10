"""Synthetic coverage for the Automatic Exhibit Engine."""

import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import exhibit_manager
import museum
from _test_support import synthetic_workspace


def artifact(number, title, artist, album, release="", duration=""):
    return {
        "Museum ID": f"MMT-{number:06d}", "Source": "Spotify",
        "Source Track ID": f"track-{number}", "Title": title, "Artist": artist,
        "Album": album, "Release Date": release, "Duration (ms)": duration,
    }


def event(number, timestamp, played=60000, **values):
    result = {
        "museum_id": f"MMT-{number:06d}", "event_timestamp": timestamp,
        "ms_played": played, "match_status": "exact_uri",
    }
    result.update(values)
    return result


def sources():
    collection = pd.DataFrame([
        artifact(1, "First", "Artist A, Guest", "Shared", "1999-01-02", "240000"),
        artifact(2, "Second", "Artist B", "Shared", "2024", "90000"),
        artifact(3, "Third", "Artist A, Guest", "Other", "2010", "180000"),
    ])
    events = [
        event(1, "2025-01-01T02:00:00Z", 240000, end_reason="trackdone",
              start_reason="clicked track", device_class="mobile", os="iOS",
              shuffle=True, offline=True),
        event(1, "2025-02-01T08:00:00Z", 1000, end_reason="forward button",
              device_class="desktop", os="Windows", shuffle=False, offline=False),
        event(1, "2025-03-01T18:00:00Z", 240000, end_reason="track completed",
              start_reason="play button", device_class="mobile", shuffle=True),
        event(1, "2025-04-05T22:00:00Z", 60000, end_reason="remote",
              device_class="desktop", shuffle=True),
        event(1, "2025-05-05T03:00:00Z", 1000, explicit_skip=True,
              device_class="mobile", offline=True),
        event(1, "2026-06-06T10:00:00Z", 240000, end_reason="endplay",
              device_class="mobile", shuffle=True),
        event(2, "2026-06-07T19:00:00Z", 90000, end_reason="trackdone",
              start_reason="clicked track", device_class="desktop"),
        event(3, "2026-07-08T12:00:00Z", 45000, device_class="mobile"),
        {"museum_id": "", "event_timestamp": "2026-01-01T01:00:00Z",
         "ms_played": 50000, "match_status": "unresolved"},
        {"museum_id": "MMT-000001", "event_timestamp": "2026-01-01T01:00:00Z",
         "ms_played": 50000, "match_status": "ambiguous"},
    ]
    manifest = pd.DataFrame([
        {"Museum ID": "MMT-000001", "Playlist ID": "p1", "Playlist Name": "One"},
        {"Museum ID": "MMT-000001", "Playlist ID": "p2", "Playlist Name": "Two"},
        {"Museum ID": "MMT-000001", "Playlist ID": "p2", "Playlist Name": "Two"},
        {"Museum ID": "MMT-000002", "Playlist ID": "p1", "Playlist Name": "One"},
    ])
    return collection, events, manifest


def exhibit_for(exhibits, metric):
    return next(item for item in exhibits if item.get("rule", {}).get("metric") == metric)


class CatalogAndMigrationTests(unittest.TestCase):
    def test_supported_catalog_is_substantial_categorized_and_idempotent(self):
        collection, events, manifest = sources()
        exhibits = exhibit_manager.create_starter_exhibits(events, [], collection, manifest)
        self.assertGreaterEqual(len(exhibits), 30)
        self.assertTrue({
            "Featured", "Listening", "Artists", "Albums", "Time", "Behavior",
            "Devices & Context", "Preservation",
        }.issubset({item["category"] for item in exhibits}))
        repeated = exhibit_manager.create_starter_exhibits(events, exhibits, collection, manifest)
        self.assertEqual(repeated, exhibits)
        self.assertEqual(len({item["exhibit_id"] for item in exhibits}), len(exhibits))

    def test_catalog_ids_are_deterministic_across_new_archives(self):
        collection, events, manifest = sources()
        first = exhibit_manager.create_starter_exhibits(events, [], collection, manifest)
        second = exhibit_manager.create_starter_exhibits(events, [], collection, manifest)
        self.assertEqual(
            {item["rule"]["catalog_key"]: item["exhibit_id"] for item in first},
            {item["rule"]["catalog_key"]: item["exhibit_id"] for item in second},
        )

    def test_v1_migration_preserves_identity_order_membership_and_notes(self):
        curated = exhibit_manager.create_exhibit(
            "Handmade", "curated", artifact_ids=["MMT-000002"], notes="keep this"
        )
        old = dict(curated)
        old["exhibit_version"] = "1"
        for field in ("category", "featured", "display_preferences"):
            old.pop(field)
        with synthetic_workspace() as root:
            path = os.path.join(root, "exhibits.json")
            with open(path, "w", encoding="utf-8") as output:
                json.dump([old], output)
            loaded = exhibit_manager.load_exhibits(path)
            exhibit_manager.save_exhibits(loaded, path)
            reloaded = exhibit_manager.load_exhibits(path)
        self.assertEqual(reloaded[0]["exhibit_id"], curated["exhibit_id"])
        self.assertEqual(reloaded[0]["display_number"], curated["display_number"])
        self.assertEqual(reloaded[0]["artifact_ids"], ["MMT-000002"])
        self.assertEqual(reloaded[0]["notes"], "keep this")
        self.assertEqual(reloaded[0]["category"], "Curated")

    def test_catalog_refresh_never_edits_curated_or_generated_definitions(self):
        collection, events, manifest = sources()
        curated = exhibit_manager.create_exhibit(
            "Private Selection", "curated", artifact_ids=["MMT-000003"], notes="mine"
        )
        generated = exhibit_manager.create_exhibit(
            "Artist A", "generated", artist="Artist A, Guest", exhibits=[curated],
            notes="generated note stays",
        )
        refreshed = exhibit_manager.create_starter_exhibits(
            events, [curated, generated], collection, manifest
        )
        self.assertEqual(refreshed[:2], [curated, generated])
        self.assertEqual(refreshed[1]["notes"], "generated note stays")

    def test_saved_automatic_exhibit_contains_a_rule_not_derived_rows_or_events(self):
        collection, events, manifest = sources()
        exhibits = exhibit_manager.create_starter_exhibits(events, [], collection, manifest)
        with synthetic_workspace() as root:
            path = os.path.join(root, "exhibits.json")
            exhibit_manager.save_exhibits(exhibits, path)
            with open(path, "r", encoding="utf-8") as source:
                saved = source.read()
        self.assertIn('"catalog_key"', saved)
        self.assertNotIn('"rows"', saved)
        self.assertNotIn("2025-01-01T02:00:00Z", saved)
        self.assertNotIn('"ms_played"', saved)


class AggregateAndRuleTests(unittest.TestCase):
    def setUp(self):
        self.collection, self.events, self.manifest = sources()
        self.index = exhibit_manager.build_exhibit_index(
            self.collection, self.events, self.manifest
        )
        self.exhibits = exhibit_manager.create_starter_exhibits(
            self.events, [], self.collection, self.manifest
        )

    def result(self, metric):
        return exhibit_manager.evaluate_automatic_exhibit(
            exhibit_for(self.exhibits, metric), self.index
        )

    def test_only_unambiguous_preserved_identities_are_aggregated(self):
        self.assertEqual(self.index["total_events"], 10)
        self.assertEqual(self.index["resolved_events"], 8)
        row = self.result("most_played_tracks")["rows"][0]
        self.assertEqual((row["entity_id"], row["events"]), ("MMT-000001", 6))

    def test_preserved_multi_artist_credit_is_not_inferred_or_split(self):
        rows = self.result("most_played_artists")["rows"]
        labels = {row["title"] for row in rows}
        self.assertIn("Artist A, Guest", labels)
        self.assertNotIn("Artist A", labels)
        self.assertNotIn("Guest", labels)

    def test_same_named_albums_are_kept_separate_by_artist_credit(self):
        rows = [row for row in self.result("most_played_albums")["rows"] if row["title"] == "Shared"]
        self.assertEqual({row["artist"] for row in rows}, {"Artist A, Guest", "Artist B"})

    def test_play_counts_time_completions_skips_and_rate_threshold(self):
        first = self.result("most_played_tracks")["rows"][0]
        self.assertEqual(first["listening_ms"], 782000)
        self.assertEqual(first["completed"], 3)
        self.assertEqual(first["explicit_skips"], 2)
        self.assertAlmostEqual(first["skip_rate"], 2 / 6)
        second = next(row for row in self.result("most_played_tracks")["rows"] if row["entity_id"] == "MMT-000002")
        self.assertIsNone(second["skip_rate"])
        self.assertIsNone(second["completion_rate"])

    def test_time_buckets_year_month_and_timezone_policy_are_explicit(self):
        self.assertEqual(self.result("late_night")["rows"][0]["late_night"], 2)
        self.assertEqual(self.result("morning_listening")["rows"][0]["morning"], 2)
        self.assertEqual(self.result("evening_listening")["rows"][0]["evening"], 2)
        years = self.result("listening_by_year")
        self.assertEqual(years["rows"][0]["entity_id"], "2025")
        self.assertIn("UTC", years["coverage"]["timezone_policy"])
        self.assertGreaterEqual(len(self.result("listening_by_month")["rows"]), 7)

    def test_year_views_relationships_gaps_consistency_and_recent_are_dynamic(self):
        year_exhibit = exhibit_for(self.exhibits, "listening_in_year")
        year_result = exhibit_manager.evaluate_automatic_exhibit(year_exhibit, self.index)
        self.assertEqual(year_result["rows"][0]["entity_id"], "MMT-000001")
        self.assertGreater(self.result("longest_relationships")["rows"][0]["relationship_days"], 500)
        self.assertGreater(self.result("returned_after_gap")["rows"][0]["longest_gap_days"], 120)
        self.assertEqual(self.result("most_consistent")["rows"][0]["distinct_months"], 6)
        self.assertEqual(self.result("recent_listening")["rows"][0]["entity_id"], "MMT-000003")

    def test_behavior_device_and_context_fields_remain_distinct(self):
        first = self.result("direct_selection")["rows"][0]
        self.assertEqual(first["direct_selection"], 2)
        self.assertEqual(self.result("mobile_listening")["rows"][0]["mobile"], 4)
        self.assertEqual(self.result("desktop_listening")["rows"][0]["desktop"], 2)
        self.assertEqual(self.result("offline_listening")["rows"][0]["offline"], 2)
        self.assertEqual(self.result("shuffle_listening")["rows"][0]["shuffle"], 4)

    def test_manifest_release_and_duration_exhibits_use_preserved_metadata(self):
        first = self.result("playlist_mainstays")["rows"][0]
        self.assertEqual((first["entity_id"], first["playlist_count"]), ("MMT-000001", 2))
        self.assertEqual(self.result("repeated_collection")["rows"][0]["occurrence_count"], 3)
        self.assertEqual(self.result("oldest_releases")["rows"][0]["entity_id"], "MMT-000001")
        self.assertEqual(self.result("newest_releases")["rows"][0]["entity_id"], "MMT-000002")
        self.assertEqual(self.result("longest_tracks")["rows"][0]["duration_ms"], 240000)
        self.assertEqual(self.result("shortest_tracks")["rows"][0]["duration_ms"], 90000)

    def test_rebuilding_index_refreshes_results_without_mutating_definition(self):
        definition = exhibit_for(self.exhibits, "most_played_tracks")
        before = exhibit_manager.evaluate_automatic_exhibit(definition, self.index)["rows"][0]["events"]
        changed = self.events + [event(1, "2026-08-01T12:00:00Z")]
        after_index = exhibit_manager.build_exhibit_index(self.collection, changed, self.manifest)
        after = exhibit_manager.evaluate_automatic_exhibit(definition, after_index)["rows"][0]["events"]
        self.assertEqual((before, after), (6, 7))
        self.assertNotIn("rows", definition)

    def test_sparse_optional_fields_do_not_invent_zeros_or_rates(self):
        sparse = [event(2, "2026-01-01", played=None)]
        index = exhibit_manager.build_exhibit_index(self.collection, sparse)
        definition = exhibit_manager.create_exhibit(
            "Tracks", "automatic", rule={"metric": "most_played_tracks"}
        )
        row = exhibit_manager.evaluate_automatic_exhibit(definition, index)["rows"][0]
        self.assertEqual(row["known_ms"], 0)
        self.assertIsNone(row["skip_rate"])
        self.assertEqual(index["coverage"].get("device_class", 0), 0)


class PerformanceAndInterfaceTests(unittest.TestCase):
    def test_twenty_thousand_events_share_one_reusable_index(self):
        collection = pd.DataFrame([
            artifact(number, f"Track {number}", f"Artist {number % 3}", f"Album {number % 2}", "2020", "180000")
            for number in range(1, 11)
        ])
        events = [
            event((index % 10) + 1, f"2026-01-{(index % 28) + 1:02d}T{index % 24:02d}:00:00Z", 60000)
            for index in range(20000)
        ]
        index = exhibit_manager.build_exhibit_index(collection, events)
        definitions = exhibit_manager.create_starter_exhibits(events, [], collection)
        for metric in ("most_played_tracks", "most_played_artists", "most_played_albums", "late_night"):
            result = exhibit_manager.evaluate_automatic_exhibit(exhibit_for(definitions, metric), index)
            self.assertTrue(result["rows"])
        self.assertEqual(index["resolved_events"], 20000)
        self.assertEqual(sum(stat["events"] for stat in index["track_stats"].values()), 20000)

    def test_home_browse_story_coverage_and_artifact_drilldown(self):
        collection, events, manifest = sources()
        exhibits = exhibit_manager.create_starter_exhibits(events, [], collection, manifest)
        most_played = exhibit_for(exhibits, "most_played_tracks")
        output = StringIO()
        with redirect_stdout(output):
            museum._print_home(collection, events, exhibits, manifest)
        self.assertIn("FEATURED EXHIBITS", output.getvalue())
        output = StringIO()
        with patch("builtins.input", side_effect=[str(most_played["display_number"]), "1"]), redirect_stdout(output):
            museum._browse_exhibits(collection, events, exhibits, manifest)
        visible = output.getvalue()
        self.assertIn("BROWSE EXHIBITS", visible)
        self.assertIn("QUICK STORY", visible)
        self.assertIn("Coverage: 8 of 10", visible)
        self.assertIn("MUSEUM RECORD", visible)

    def test_exhibit_rows_drill_into_artist_and_disambiguated_album_views(self):
        collection, events, manifest = sources()
        exhibits = exhibit_manager.create_starter_exhibits(events, [], collection, manifest)
        artist_exhibit = exhibit_for(exhibits, "most_played_artists")
        album_exhibit = exhibit_for(exhibits, "most_played_albums")
        with patch("museum._show_entity") as show, patch(
            "builtins.input", side_effect=[str(artist_exhibit["display_number"]), "1"]
        ):
            museum._browse_exhibits(collection, events, exhibits, manifest)
        show.assert_called_once_with(collection, events, "artist", "Artist A, Guest")
        with patch("museum._show_entity") as show, patch(
            "builtins.input", side_effect=[str(album_exhibit["display_number"]), "1"]
        ):
            museum._browse_exhibits(collection, events, exhibits, manifest)
        show.assert_called_once_with(collection, events, "album", "Shared", "Artist A, Guest")


if __name__ == "__main__":
    unittest.main()
