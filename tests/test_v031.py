"""Regression tests for the v0.3.1 validation and hardening pass."""

import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pandas as pd


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

from archive import _merge_artifacts, _print_report
from collection_manager import (
    COLLECTION_COLUMNS,
    assert_valid_collection,
    build_collection,
    collections_semantically_equal,
    save_collection,
    validate_collection,
)
from spotify_api import classify_playlist_entries


def artifact(track_id="track-1", popularity=""):
    return {
        "Spotify ID": track_id,
        "Title": "Title",
        "Artist": "Artist",
        "Album": "Album",
        "Release Date": "2020",
        "Duration (ms)": "1000",
        "Popularity": popularity,
        "Spotify URL": f"https://open.spotify.com/track/{track_id}",
    }


def existing_collection():
    row = {
        "Museum ID": "MMT-000001",
        "Source": "Spotify",
        "Source Track ID": "track-1",
        "Title": "Title",
        "Artist": "Artist",
        "Album": "Album",
        "Release Date": "2020",
        "Duration (ms)": "1000",
        "Popularity": "",
        "Spotify URL": "https://open.spotify.com/track/track-1",
        "Archived At": "2026-07-24 11:25:44",
        "Toolkit Version": "0.2",
        "Status": "Available",
        "Notes": "user note",
    }
    return pd.DataFrame([row], columns=COLLECTION_COLUMNS)


def playlist_track(track_id="track-1", popularity=None):
    return {
        "track": {
            "id": track_id,
            "type": "track",
            "is_local": False,
            "name": "Title",
            "artists": [{"name": "Artist"}],
            "album": {"name": "Album", "release_date": "2020"},
            "duration_ms": 1000,
            "popularity": popularity,
            "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
        }
    }


class CollectionValidationTests(unittest.TestCase):
    def test_duplicate_museum_id_rejected(self):
        collection = pd.concat(
            [existing_collection(), existing_collection().assign(
                **{"Source Track ID": "track-2"}
            )],
            ignore_index=True,
        )
        self.assertIn("Museum IDs must be unique", validate_collection(collection))

    def test_duplicate_source_track_rejected(self):
        collection = pd.concat(
            [existing_collection(), existing_collection().assign(
                **{"Museum ID": "MMT-000002"}
            )],
            ignore_index=True,
        )
        self.assertIn(
            "Spotify source track IDs must be unique",
            validate_collection(collection),
        )

    def test_invalid_museum_id_format_rejected(self):
        collection = existing_collection()
        collection.loc[0, "Museum ID"] = "MMT-1"
        self.assertIn(
            "Museum IDs must match MMT- followed by six digits",
            validate_collection(collection),
        )

    def test_existing_identity_timestamp_notes_and_version_are_preserved(self):
        old = existing_collection()
        result = build_collection([artifact()], old)
        for field in ("Museum ID", "Archived At", "Notes", "Toolkit Version"):
            self.assertEqual(result.loc[0, field], old.loc[0, field])
        self.assertEqual(validate_collection(result, old), [])

    def test_changes_to_protected_existing_values_are_rejected(self):
        old = existing_collection()
        for field, value in (
            ("Museum ID", "MMT-000002"),
            ("Archived At", "2099-01-01 00:00:00"),
            ("Notes", "overwritten"),
        ):
            with self.subTest(field=field):
                changed = old.copy()
                changed.loc[0, field] = value
                errors = validate_collection(changed, old)
                self.assertTrue(any(field in error for error in errors))

    def test_unchanged_sync_is_idempotent(self):
        old = existing_collection()
        first = build_collection([artifact()], old)
        second = build_collection([artifact()], first)
        pd.testing.assert_frame_equal(first, second)

    def test_invalid_and_empty_collections_do_not_replace_saved_file(self):
        old = existing_collection()
        with patch("collection_manager._atomic_save") as atomic_save:
            with self.assertRaises(ValueError):
                save_collection(pd.DataFrame(columns=COLLECTION_COLUMNS), old)
        atomic_save.assert_not_called()

    def test_unchanged_valid_collection_is_not_rewritten(self):
        old = existing_collection()
        output = StringIO()
        with (
            patch("collection_manager.os.path.exists", return_value=True),
            patch("collection_manager._read_csv_if_present", return_value=old),
            patch("collection_manager._atomic_save") as atomic_save,
            redirect_stdout(output),
        ):
            save_collection(old, old)
        atomic_save.assert_not_called()
        self.assertIn("Collection unchanged:", output.getvalue())
        self.assertIn("was validated and not rewritten.", output.getvalue())

    def test_semantic_representation_differences_do_not_trigger_rewrite(self):
        saved = existing_collection()
        candidate = saved.copy()
        candidate["Duration (ms)"] = candidate["Duration (ms)"].astype(int)
        candidate.index = [99]
        candidate = candidate[list(reversed(COLLECTION_COLUMNS))]
        self.assertTrue(collections_semantically_equal(saved, candidate))

        with (
            patch("collection_manager.os.path.exists", return_value=True),
            patch("collection_manager._read_csv_if_present", return_value=saved),
            patch("collection_manager._atomic_save") as atomic_save,
            redirect_stdout(StringIO()),
        ):
            save_collection(candidate, saved)
        atomic_save.assert_not_called()

    def test_genuinely_changed_collection_is_saved(self):
        old = existing_collection()
        changed = old.copy()
        changed.loc[0, "Title"] = "Updated Title"
        output = StringIO()
        with (
            patch("collection_manager.os.path.exists", return_value=True),
            patch("collection_manager._read_csv_if_present", return_value=old),
            patch("collection_manager._atomic_save") as atomic_save,
            redirect_stdout(output),
        ):
            save_collection(changed, old)
        atomic_save.assert_called_once()
        self.assertIn("Collection saved:", output.getvalue())


class PlaylistClassificationTests(unittest.TestCase):
    def test_every_entry_is_classified(self):
        entries = [
            playlist_track("track-1"),
            playlist_track("track-1"),
            {"track": {"id": None, "type": "track", "is_local": True}},
            {"track": None},
            {"track": {"id": "episode-1", "type": "episode"}},
            {"track": {"id": None, "type": "track", "is_local": False}},
            "bad entry",
        ]
        artifacts, counts = classify_playlist_entries(entries, set())
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(sum(counts.values()), len(entries))
        self.assertEqual(counts["valid_tracks"], 1)
        self.assertEqual(counts["duplicate_tracks"], 1)
        self.assertEqual(counts["local_files"], 1)
        self.assertEqual(counts["unavailable_entries"], 1)
        self.assertEqual(counts["unsupported_entries"], 1)
        self.assertEqual(counts["malformed_entries"], 2)

    def test_null_track_is_safe(self):
        artifacts, counts = classify_playlist_entries([{"track": None}], set())
        self.assertEqual(artifacts, [])
        self.assertEqual(counts["unavailable_entries"], 1)

    def test_blank_popularity_is_optional(self):
        artifacts, counts = classify_playlist_entries(
            [playlist_track(popularity=None)], set()
        )
        self.assertEqual(counts["valid_tracks"], 1)
        self.assertEqual(artifacts[0]["Popularity"], "")

    def test_blank_popularity_does_not_erase_existing_value(self):
        current = [artifact(popularity=85)]
        changes = _merge_artifacts(current, [artifact(popularity="")])
        self.assertEqual(current[0]["Popularity"], 85)
        self.assertEqual(changes["unchanged"], 1)

    def test_report_prints_all_categories_and_checks_total(self):
        report = {
            "playlist_items_reported": 7,
            "playlist_entries_scanned": 7,
            "valid_tracks": 1,
            "new_artifacts": 0,
            "unchanged": 1,
            "metadata_updates": 0,
            "duplicate_tracks": 1,
            "local_files": 1,
            "unavailable_entries": 1,
            "unsupported_entries": 1,
            "malformed_entries": 2,
        }
        output = StringIO()
        with redirect_stdout(output):
            _print_report(report, total_artifacts=1)
        text = output.getvalue()
        for label in (
            "Valid unique Spotify tracks:",
            "Duplicate occurrences skipped:",
            "Local files skipped:",
            "Unavailable entries skipped:",
            "Unsupported entries skipped:",
            "Malformed entries skipped:",
        ):
            self.assertIn(label, text)

        report["playlist_entries_scanned"] = 8
        with self.assertRaises(ValueError):
            _print_report(report, total_artifacts=1)


if __name__ == "__main__":
    unittest.main()
