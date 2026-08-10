"""Offline Listening Archive, Inspection, and Exhibit tests."""

import json
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import exhibit_manager
import inspection_manager
import listening_archive
from collection_manager import COLLECTION_COLUMNS


def collection():
    rows = [
        {"Museum ID": "MMT-000001", "Source": "Spotify", "Source Track ID": "one",
         "Title": "Gym Class", "Artist": "Lil Peep", "Album": "Single"},
        {"Museum ID": "MMT-000002", "Source": "Spotify", "Source Track ID": "two",
         "Title": "Same Song", "Artist": "Alpha", "Album": "A"},
        {"Museum ID": "MMT-000003", "Source": "Spotify", "Source Track ID": "three",
         "Title": "Same Song", "Artist": "Beta", "Album": "B"},
    ]
    return pd.DataFrame(rows).reindex(columns=COLLECTION_COLUMNS, fill_value="")


class ListeningArchiveTests(unittest.TestCase):
    def test_validation_exact_mapping_and_unresolved_behavior(self):
        mapped = listening_archive.normalize_event(
            {"timestamp": "2026-01-01T00:00:00Z", "spotify_uri": "spotify:track:one", "ms_played": 30000},
            "synthetic", uri_index=listening_archive.collection_uri_index(collection()), imported_at="now"
        )
        self.assertEqual((mapped["museum_id"], mapped["match_status"]), ("MMT-000001", "exact_uri"))
        unresolved = listening_archive.normalize_event(
            {"timestamp": "2026-01-01T00:00:01Z", "spotify_uri": "spotify:track:missing"}, "synthetic"
        )
        self.assertEqual(unresolved["match_status"], "unresolved")
        with self.assertRaises(ValueError):
            listening_archive.normalize_event({}, "synthetic")

    def test_idempotent_import_and_corrupt_archive(self):
        path = os.path.join(ROOT, "tests", "_events_test.jsonl")
        try:
            raw = [{"timestamp": "2026-01-01", "spotify_uri": "spotify:track:one", "ms_played": 1}]
            first = listening_archive.import_events(raw, "synthetic", collection(), path=path, imported_at="now")
            second = listening_archive.import_events(raw, "synthetic", collection(), path=path, imported_at="later")
            self.assertEqual((first["added"], second["added"], second["total"]), (1, 0, 1))
            with open(path, "w", encoding="utf-8") as output: output.write("not json")
            with self.assertRaises(ValueError): listening_archive.load_events(path)
            with open(path, "w", encoding="utf-8") as output: output.write("[]\n")
            with self.assertRaises(ValueError): listening_archive.load_events(path)
        finally:
            if os.path.exists(path): os.remove(path)

    def test_classifications_are_explicit(self):
        cases = [
            ({"ms_played": 1000, "explicit_skip": True}, "explicit_skip"),
            ({"ms_played": 1000, "end_reason": "track completed"}, "completed_play"),
            ({"ms_played": 30000}, "meaningful_play"), ({"ms_played": 29999}, "short_play"),
            ({"ms_played": None}, "interrupted_or_other"),
        ]
        for event, expected in cases:
            self.assertEqual(listening_archive.classify_playback(event), expected)


class InspectionTests(unittest.TestCase):
    def test_search_ranking_duplicates_artist_and_combination(self):
        self.assertEqual(inspection_manager.search_artifacts(collection(), "lil peep gym class")[0]["Museum ID"], "MMT-000001")
        self.assertEqual(len(inspection_manager.search_artifacts(collection(), "same song")), 2)
        self.assertEqual(inspection_manager.search_artifacts(collection(), "Beta")[0]["Museum ID"], "MMT-000003")


class ExhibitTests(unittest.TestCase):
    def test_identity_numbering_persistence_and_recalculation(self):
        first = exhibit_manager.create_exhibit("Top", "automatic", rule={"metric": "most_played_artists"})
        second = exhibit_manager.create_exhibit("Curated", "curated", artifact_ids=["MMT-000001"], exhibits=[first])
        self.assertNotEqual(first["exhibit_id"], second["exhibit_id"])
        self.assertEqual([first["display_number"], second["display_number"]], [1, 2])
        path = os.path.join(ROOT, "tests", "_exhibits_test.json")
        try:
            exhibit_manager.save_exhibits([first, second], path)
            loaded = exhibit_manager.load_exhibits(path)
        finally:
            if os.path.exists(path): os.remove(path)
        self.assertEqual(loaded[1]["artifact_ids"], ["MMT-000001"])
        events = [{"artist": "A"}, {"artist": "A"}, {"artist": "B"}]
        self.assertEqual(exhibit_manager.automatic_results(first, events)[0], ("A", 2))
        self.assertEqual(exhibit_manager.automatic_results(first, events + [{"artist": "B"}, {"artist": "B"}])[0], ("B", 3))


if __name__ == "__main__": unittest.main()
