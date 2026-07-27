"""Offline regression tests for occurrence-level playlist manifests."""

import os
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import pandas as pd


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import archive
import manifest_manager
from collection_manager import COLLECTION_COLUMNS
from manifest_manager import (
    MANIFEST_COLUMNS,
    assert_valid_manifest,
    map_museum_ids,
    validate_manifest,
    validate_manifest_checkpoint,
)
from spotify_api import classify_playlist_occurrences, get_playlist_summary


PLAYLIST_ID = archive.PLAYLIST_ID
PLAYLIST_NAME = "Museum Playlist"
SNAPSHOT_ID = "snapshot-1"
CAPTURED_AT = "2026-07-26T12:00:00+00:00"


def collection():
    rows = []
    for number, track_id in enumerate(("track-1", "track-2"), start=1):
        rows.append({
            "Museum ID": f"MMT-{number:06}",
            "Source": "Spotify",
            "Source Track ID": track_id,
            "Title": f"Title {number}",
            "Artist": "Artist",
            "Album": "Album",
            "Release Date": "2020",
            "Duration (ms)": "1000",
            "Popularity": "",
            "Spotify URL": f"https://open.spotify.com/track/{track_id}",
            "Archived At": "2026-07-24 11:25:44",
            "Toolkit Version": "0.2",
            "Status": "Available",
            "Notes": "",
        })
    return pd.DataFrame(rows, columns=COLLECTION_COLUMNS)


def track(track_id="track-1", **overrides):
    item = {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "type": "track",
        "is_local": False,
        "name": "Track",
        "artists": [{"name": "Artist"}],
        "album": {"name": "Album"},
        "duration_ms": 1000,
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
    }
    item.update(overrides)
    return {"added_at": "2026-07-25T00:00:00Z", "track": item}


def occurrence_fixture():
    entries = [
        track(),
        track(),
        track(None, is_local=True, uri="spotify:local:x", name="Local"),
        {"added_at": "2026-07-25T00:00:03Z", "track": None},
        {"track": {
            "id": "episode-1",
            "uri": "spotify:episode:episode-1",
            "type": "episode",
            "name": "Episode",
            "show": {"name": "Show"},
        }},
        {"track": {"id": None, "type": "track", "name": "Broken"}},
        "not an object",
    ]
    artifacts, counts, rows = classify_playlist_occurrences(
        entries,
        1,
        PLAYLIST_ID,
        PLAYLIST_NAME,
        SNAPSHOT_ID,
        CAPTURED_AT,
        {},
    )
    return artifacts, counts, pd.DataFrame(rows, columns=MANIFEST_COLUMNS)


def report_from_counts(counts, scanned):
    report = {
        "playlist_items_reported": scanned,
        "playlist_entries_scanned": scanned,
        "new_artifacts": 0,
        "metadata_updates": 0,
        "unchanged": 0,
    }
    report.update(counts)
    return report


class OccurrenceClassificationTests(unittest.TestCase):
    def test_playlist_summary_requests_and_returns_playlist_id(self):
        spotify = Mock()
        spotify.playlist.return_value = {
            "id": PLAYLIST_ID,
            "name": PLAYLIST_NAME,
            "snapshot_id": SNAPSHOT_ID,
            "items": {"total": 7},
        }
        summary = get_playlist_summary(spotify, PLAYLIST_ID)
        self.assertEqual(summary["playlist_id"], PLAYLIST_ID)
        spotify.playlist.assert_called_once_with(
            PLAYLIST_ID,
            fields="id,name,snapshot_id,items.total",
        )

    def test_one_row_per_occurrence_with_exact_positions_and_categories(self):
        artifacts, counts, manifest = occurrence_fixture()
        self.assertEqual(len(manifest), 7)
        self.assertEqual(manifest["Playlist Position"].tolist(), list(range(1, 8)))
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(sum(counts.values()), 7)
        self.assertEqual(
            manifest["Classification"].tolist(),
            [
                "valid track",
                "duplicate occurrence",
                "local file",
                "unavailable entry",
                "unsupported entry",
                "malformed entry",
                "malformed entry",
            ],
        )

    def test_duplicate_linkage_and_museum_mapping(self):
        _, _, manifest = occurrence_fixture()
        mapped = map_museum_ids(manifest, collection())
        first, duplicate = mapped.iloc[0], mapped.iloc[1]
        self.assertEqual(str(duplicate["Duplicate Of Position"]), "1")
        self.assertEqual(first["Museum ID"], "MMT-000001")
        self.assertEqual(duplicate["Museum ID"], first["Museum ID"])
        self.assertEqual(duplicate["Source Track ID"], first["Source Track ID"])

    def test_safe_metadata_and_nonrestorable_reasons_are_preserved(self):
        _, _, manifest = occurrence_fixture()
        local = manifest.iloc[2]
        unsupported = manifest.iloc[4]
        self.assertEqual(local["Title"], "Local")
        self.assertEqual(local["Spotify URI"], "spotify:local:x")
        self.assertEqual(local["Added At"], "2026-07-25T00:00:00Z")
        self.assertEqual(unsupported["Artist"], "Show")
        for index in range(2, 7):
            self.assertEqual(manifest.iloc[index]["Restorable"], "False")
            self.assertTrue(manifest.iloc[index]["Reason"])


class ManifestValidationTests(unittest.TestCase):
    def valid_manifest(self):
        _, counts, manifest = occurrence_fixture()
        manifest = map_museum_ids(manifest, collection())
        return manifest, report_from_counts(counts, len(manifest))

    def test_valid_manifest_reconciles_classification_totals(self):
        manifest, report = self.valid_manifest()
        self.assertEqual(
            validate_manifest(
                manifest,
                collection(),
                PLAYLIST_ID,
                PLAYLIST_NAME,
                SNAPSHOT_ID,
                report,
            ),
            [],
        )

    def test_validation_rejects_required_integrity_failures(self):
        valid, report = self.valid_manifest()
        mutations = {
            "empty": valid.iloc[0:0],
            "duplicate position": valid.assign(
                **{"Playlist Position": [1, 1, 3, 4, 5, 6, 7]}
            ),
            "unknown classification": valid.assign(
                **{"Classification": [
                    "unknown", *valid["Classification"].tolist()[1:]
                ]}
            ),
            "wrong snapshot": valid.assign(**{"Snapshot ID": "other"}),
            "restorable without identity": valid.assign(
                **{"Source Track ID": [
                    "", *valid["Source Track ID"].tolist()[1:]
                ]}
            ),
            "bad duplicate link": valid.assign(
                **{"Duplicate Of Position": ["", 2, "", "", "", "", ""]}
            ),
        }
        for label, changed in mutations.items():
            with self.subTest(label=label):
                self.assertTrue(validate_manifest(
                    changed,
                    collection(),
                    PLAYLIST_ID,
                    PLAYLIST_NAME,
                    SNAPSHOT_ID,
                    report,
                ))

        wrong_report = dict(report, duplicate_tracks=0)
        with self.assertRaises(ValueError):
            assert_valid_manifest(
                valid,
                collection(),
                PLAYLIST_ID,
                PLAYLIST_NAME,
                SNAPSHOT_ID,
                wrong_report,
            )

    def test_checkpoint_accepts_same_snapshot_and_rejects_changed_snapshot(self):
        manifest, report = self.valid_manifest()
        self.assertTrue(validate_manifest_checkpoint(
            manifest, PLAYLIST_ID, PLAYLIST_NAME, SNAPSHOT_ID, report
        ))
        self.assertFalse(validate_manifest_checkpoint(
            manifest, PLAYLIST_ID, PLAYLIST_NAME, "changed", report
        ))

    def test_interrupted_manifest_checkpoint_is_saved_and_restored(self):
        manifest, report = self.valid_manifest()
        checkpoint_path = "playlist_manifest.checkpoint.csv"
        with (
            patch("manifest_manager._output_path", return_value=checkpoint_path),
            patch("manifest_manager._atomic_save") as atomic_save,
            patch("manifest_manager._read", return_value=manifest.copy()),
        ):
            manifest_manager.save_manifest_checkpoint(manifest)
            restored = manifest_manager.load_manifest_checkpoint()
        atomic_save.assert_called_once_with(manifest, checkpoint_path)
        self.assertTrue(validate_manifest_checkpoint(
            restored, PLAYLIST_ID, PLAYLIST_NAME, SNAPSHOT_ID, report
        ))
        self.assertEqual(
            restored["Playlist Position"].astype(int).tolist(),
            list(range(1, len(manifest) + 1)),
        )

    def test_checkpoint_rejects_fractional_and_broken_positions(self):
        valid, report = self.valid_manifest()
        mutations = (
            valid.assign(**{"Playlist Position": [
                value + 0.5 for value in range(1, len(valid) + 1)
            ]}),
            valid.assign(**{"Playlist Position": [1, 1, 3, 4, 5, 6, 7]}),
            valid.assign(**{"Playlist Position": [2, 1, 3, 4, 5, 6, 7]}),
            valid.assign(**{"Playlist Position": [1, 2, 3, 4, 5, 6, 8]}),
        )
        for changed in mutations:
            with self.subTest(positions=changed["Playlist Position"].tolist()):
                self.assertFalse(validate_manifest_checkpoint(
                    changed,
                    PLAYLIST_ID,
                    PLAYLIST_NAME,
                    SNAPSHOT_ID,
                    report,
                ))

    def test_checkpoint_rejects_report_capture_and_duplicate_corruption(self):
        valid, report = self.valid_manifest()
        bad_report = dict(report, duplicate_tracks=0)
        missing_capture = valid.copy()
        missing_capture.loc[0, "Captured At"] = ""
        inconsistent_capture = valid.copy()
        inconsistent_capture.loc[1, "Captured At"] = "different"
        bad_duplicate = valid.copy()
        bad_duplicate.loc[1, "Duplicate Of Position"] = "2"
        for label, changed, saved_report in (
            ("report totals", valid, bad_report),
            ("missing capture", missing_capture, report),
            ("inconsistent capture", inconsistent_capture, report),
            ("duplicate linkage", bad_duplicate, report),
        ):
            with self.subTest(label=label):
                self.assertFalse(validate_manifest_checkpoint(
                    changed,
                    PLAYLIST_ID,
                    PLAYLIST_NAME,
                    SNAPSHOT_ID,
                    saved_report,
                ))

    def test_atomic_write_failure_leaves_permanent_manifest_unchanged(self):
        manifest, _ = self.valid_manifest()
        path = os.path.join(ROOT, "Output", "playlist_manifest.csv")
        with (
            patch.object(pd.DataFrame, "to_csv") as to_csv,
            patch("manifest_manager.os.makedirs"),
            patch("manifest_manager.os.replace", side_effect=OSError("fail")),
        ):
            with self.assertRaises(OSError):
                manifest_manager._atomic_save(manifest, path)
        to_csv.assert_called_once_with(path + ".tmp", index=False)

    def test_matching_manifest_is_not_rewritten(self):
        manifest, report = self.valid_manifest()
        with (
            patch("manifest_manager.os.path.exists", return_value=True),
            patch("manifest_manager._read", return_value=manifest.copy()),
            patch("manifest_manager._atomic_save") as atomic_save,
            redirect_stdout(StringIO()),
        ):
            manifest_manager.save_manifest(
                manifest,
                collection(),
                PLAYLIST_ID,
                PLAYLIST_NAME,
                SNAPSHOT_ID,
                report,
            )
        atomic_save.assert_not_called()


class ArchiveManifestFlowTests(unittest.TestCase):
    def complete_state(self, report):
        return {
            "playlist_id": PLAYLIST_ID,
            "complete_snapshot": SNAPSHOT_ID,
            "last_report": report,
        }

    def run_completed_scan(
        self,
        final_summary,
        entries=None,
        initial_total=1,
        scanned=None,
        rows_override=None,
        counts_override=None,
        state=None,
    ):
        entries = entries if entries is not None else [track()]
        page_artifacts, counts, rows = classify_playlist_occurrences(
            entries, 1, PLAYLIST_ID, PLAYLIST_NAME, SNAPSHOT_ID, CAPTURED_AT, {}
        )
        page_counts = counts_override if counts_override is not None else counts
        page_rows = rows if rows_override is None else rows_override
        page_scanned = len(entries) if scanned is None else scanned
        initial_summary = {
            "playlist_id": PLAYLIST_ID,
            "name": PLAYLIST_NAME,
            "snapshot_id": SNAPSHOT_ID,
            "total": initial_total,
        }
        output = StringIO()
        stack = ExitStack()
        with stack, redirect_stdout(output):
            stack.enter_context(patch(
                "archive.load_existing_collection", return_value=collection()
            ))
            stack.enter_context(patch(
                "archive.load_checkpoint", return_value=pd.DataFrame()
            ))
            stack.enter_context(patch(
                "archive.load_manifest",
                return_value=pd.DataFrame(columns=MANIFEST_COLUMNS),
            ))
            stack.enter_context(patch(
                "archive.load_manifest_checkpoint",
                return_value=pd.DataFrame(columns=MANIFEST_COLUMNS),
            ))
            stack.enter_context(patch(
                "archive._load_state", return_value=state if state is not None else {}
            ))
            stack.enter_context(patch("archive.connect_spotify", return_value=object()))
            stack.enter_context(patch(
                "archive.get_playlist_summary",
                side_effect=[initial_summary, final_summary],
            ))
            get_page_mock = stack.enter_context(patch(
                "archive.get_playlist_page_occurrences",
                return_value=(
                    page_artifacts,
                    None,
                    page_counts,
                    page_scanned,
                    page_rows,
                ),
            ))
            stack.enter_context(patch("archive._checkpoint"))
            save_collection_mock = stack.enter_context(
                patch("archive.save_collection")
            )
            save_manifest_mock = stack.enter_context(patch("archive.save_manifest"))
            remove_checkpoint_mock = stack.enter_context(
                patch("archive.remove_checkpoint")
            )
            remove_manifest_checkpoint_mock = stack.enter_context(
                patch("archive.remove_manifest_checkpoint")
            )
            save_state_mock = stack.enter_context(patch("archive._save_state"))
            stack.enter_context(patch("archive.tqdm"))
            archive.main()
        return {
            "save_collection": save_collection_mock,
            "save_manifest": save_manifest_mock,
            "save_state": save_state_mock,
            "remove_checkpoint": remove_checkpoint_mock,
            "remove_manifest_checkpoint": remove_manifest_checkpoint_mock,
            "get_page": get_page_mock,
            "output": output.getvalue(),
        }

    def test_stable_final_snapshot_completes_normally(self):
        result = self.run_completed_scan({
            "playlist_id": PLAYLIST_ID,
            "name": PLAYLIST_NAME,
            "snapshot_id": SNAPSHOT_ID,
            "total": 1,
        })
        result["save_collection"].assert_called_once()
        result["save_manifest"].assert_called_once()
        result["save_state"].assert_called_once()

    def test_short_stable_scan_is_invalidated_and_next_run_starts_clean(self):
        stable_summary = {
            "playlist_id": PLAYLIST_ID,
            "name": PLAYLIST_NAME,
            "snapshot_id": SNAPSHOT_ID,
            "total": 3,
        }
        incomplete = self.run_completed_scan(
            stable_summary,
            entries=[track("track-1"), track("track-2")],
            initial_total=3,
        )
        incomplete["save_collection"].assert_not_called()
        incomplete["save_manifest"].assert_not_called()
        incomplete["save_state"].assert_called_once_with({})
        incomplete["remove_checkpoint"].assert_called_once()
        incomplete["remove_manifest_checkpoint"].assert_called_once()
        self.assertIn("incomplete occurrence scan", incomplete["output"])

        clean_state = incomplete["save_state"].call_args.args[0]
        following = self.run_completed_scan(
            {
                "playlist_id": PLAYLIST_ID,
                "name": PLAYLIST_NAME,
                "snapshot_id": SNAPSHOT_ID,
                "total": 1,
            },
            state=clean_state,
        )
        self.assertEqual(following["get_page"].call_args.args[2], 0)
        self.assertEqual(following["get_page"].call_args.args[4], 1)

    def test_manifest_row_count_mismatch_cannot_complete(self):
        result = self.run_completed_scan(
            {
                "playlist_id": PLAYLIST_ID,
                "name": PLAYLIST_NAME,
                "snapshot_id": SNAPSHOT_ID,
                "total": 1,
            },
            rows_override=[],
        )
        result["save_collection"].assert_not_called()
        result["save_manifest"].assert_not_called()
        result["save_state"].assert_called_once_with({})

    def test_classification_total_mismatch_cannot_complete(self):
        bad_counts = {
            "valid_tracks": 1,
            "duplicate_tracks": 1,
            "local_files": 0,
            "unavailable_entries": 0,
            "unsupported_entries": 0,
            "malformed_entries": 0,
        }
        result = self.run_completed_scan(
            {
                "playlist_id": PLAYLIST_ID,
                "name": PLAYLIST_NAME,
                "snapshot_id": SNAPSHOT_ID,
                "total": 1,
            },
            counts_override=bad_counts,
        )
        result["save_collection"].assert_not_called()
        result["save_manifest"].assert_not_called()
        result["save_state"].assert_called_once_with({})

    def test_nonartifact_occurrences_count_toward_complete_scan(self):
        entries = [
            track("track-1"),
            track("track-1"),
            track(None, is_local=True, uri="spotify:local:x"),
            {"track": None},
            {"track": {
                "id": "episode-1",
                "uri": "spotify:episode:episode-1",
                "type": "episode",
                "name": "Episode",
                "show": {"name": "Show"},
            }},
        ]
        summary = {
            "playlist_id": PLAYLIST_ID,
            "name": PLAYLIST_NAME,
            "snapshot_id": SNAPSHOT_ID,
            "total": len(entries),
        }
        result = self.run_completed_scan(
            summary,
            entries=entries,
            initial_total=len(entries),
        )
        result["save_collection"].assert_called_once()
        result["save_manifest"].assert_called_once()
        result["save_state"].assert_called_once()

    def test_changed_final_context_prevents_permanent_completion(self):
        changes = {
            "snapshot": {
                "playlist_id": PLAYLIST_ID,
                "name": PLAYLIST_NAME,
                "snapshot_id": "changed",
                "total": 1,
            },
            "total": {
                "playlist_id": PLAYLIST_ID,
                "name": PLAYLIST_NAME,
                "snapshot_id": SNAPSHOT_ID,
                "total": 2,
            },
            "name": {
                "playlist_id": PLAYLIST_ID,
                "name": "Renamed",
                "snapshot_id": SNAPSHOT_ID,
                "total": 1,
            },
            "playlist ID": {
                "playlist_id": "other",
                "name": PLAYLIST_NAME,
                "snapshot_id": SNAPSHOT_ID,
                "total": 1,
            },
        }
        for label, final_summary in changes.items():
            with self.subTest(label=label):
                result = self.run_completed_scan(final_summary)
                result["save_collection"].assert_not_called()
                result["save_manifest"].assert_not_called()
                result["save_state"].assert_not_called()
                self.assertIn("changed during scanning", result["output"])

    def test_rate_limit_during_final_verification_preserves_recoverability(self):
        result = self.run_completed_scan(archive.SpotifyRateLimit(120))
        result["save_collection"].assert_not_called()
        result["save_manifest"].assert_not_called()
        result["save_state"].assert_not_called()
        self.assertIn("final snapshot verification", result["output"])

    def test_other_final_verification_failure_prevents_completion(self):
        result = self.run_completed_scan(RuntimeError("verification unavailable"))
        result["save_collection"].assert_not_called()
        result["save_manifest"].assert_not_called()
        result["save_state"].assert_not_called()
        self.assertIn("Final snapshot verification failed", result["output"])

    def test_checkpoint_state_uses_manifest_positions_not_seen_track_ids(self):
        report = report_from_counts(
            {
                "valid_tracks": 0,
                "duplicate_tracks": 0,
                "local_files": 0,
                "unavailable_entries": 0,
                "unsupported_entries": 0,
                "malformed_entries": 0,
            },
            0,
        )
        with (
            patch("archive.save_manifest_checkpoint"),
            patch("archive.save_checkpoint"),
            patch("archive._save_state") as save_state,
        ):
            archive._checkpoint(
                [],
                pd.DataFrame(),
                pd.DataFrame(columns=MANIFEST_COLUMNS),
                PLAYLIST_NAME,
                SNAPSHOT_ID,
                CAPTURED_AT,
                0,
                0,
                report,
            )
        saved_state = save_state.call_args.args[0]
        self.assertNotIn("seen_track_ids", saved_state)

    def test_matching_manifest_retains_completed_snapshot_shortcut(self):
        _, counts, raw = classify_playlist_occurrences(
            [track()], 1, PLAYLIST_ID, PLAYLIST_NAME, SNAPSHOT_ID, CAPTURED_AT, {}
        )
        manifest = map_museum_ids(
            pd.DataFrame(raw, columns=MANIFEST_COLUMNS), collection()
        )
        report = report_from_counts(counts, 1)
        with (
            patch("archive.load_existing_collection", return_value=collection()),
            patch("archive.load_checkpoint", return_value=pd.DataFrame()),
            patch("archive.load_manifest", return_value=manifest),
            patch("archive.load_manifest_checkpoint", return_value=pd.DataFrame()),
            patch("archive._load_state", return_value=self.complete_state(report)),
            patch("archive.connect_spotify", return_value=object()),
            patch("archive.get_playlist_summary", return_value={
                "name": PLAYLIST_NAME, "snapshot_id": SNAPSHOT_ID, "total": 1
            }),
            patch("archive.get_playlist_page_occurrences") as get_page,
            patch("archive.save_collection"),
            patch("archive.save_manifest") as save_manifest_mock,
            redirect_stdout(StringIO()),
        ):
            archive.main()
        get_page.assert_not_called()
        save_manifest_mock.assert_called_once()

    def test_missing_manifest_forces_full_scan(self):
        page_artifact = {
            "Spotify ID": "track-1",
            "Title": "Track",
            "Artist": "Artist",
            "Album": "Album",
            "Release Date": "",
            "Duration (ms)": 1000,
            "Popularity": "",
            "Spotify URL": "https://open.spotify.com/track/track-1",
        }
        _, counts, raw = classify_playlist_occurrences(
            [track()], 1, PLAYLIST_ID, PLAYLIST_NAME, SNAPSHOT_ID, CAPTURED_AT, {}
        )
        report = report_from_counts(counts, 1)
        with (
            patch("archive.load_existing_collection", return_value=collection()),
            patch("archive.load_checkpoint", return_value=pd.DataFrame()),
            patch("archive.load_manifest", return_value=pd.DataFrame(
                columns=MANIFEST_COLUMNS
            )),
            patch("archive.load_manifest_checkpoint", return_value=pd.DataFrame()),
            patch("archive._load_state", return_value=self.complete_state(report)),
            patch("archive.connect_spotify", return_value=object()),
            patch("archive.get_playlist_summary", return_value={
                "name": PLAYLIST_NAME, "snapshot_id": SNAPSHOT_ID, "total": 1
            }),
            patch("archive.get_playlist_page_occurrences", return_value=(
                [page_artifact], None, counts, 1, raw
            )) as get_page,
            patch("archive._checkpoint"),
            patch("archive.save_collection"),
            patch("archive.save_manifest"),
            patch("archive.remove_checkpoint"),
            patch("archive.remove_manifest_checkpoint"),
            patch("archive._save_state"),
            patch("archive.tqdm") as progress,
            redirect_stdout(StringIO()),
        ):
            progress.return_value.update.return_value = None
            archive.main()
        get_page.assert_called_once()

    def test_interrupted_scan_restores_checkpoint_and_next_position(self):
        first_artifacts, first_counts, first_rows = classify_playlist_occurrences(
            [track("track-1")],
            1,
            PLAYLIST_ID,
            PLAYLIST_NAME,
            SNAPSHOT_ID,
            CAPTURED_AT,
            {},
        )
        _, second_counts, second_rows = classify_playlist_occurrences(
            [track("track-2")],
            2,
            PLAYLIST_ID,
            PLAYLIST_NAME,
            SNAPSHOT_ID,
            CAPTURED_AT,
            {"track-1": 1},
        )
        checkpoint_manifest = pd.DataFrame(first_rows, columns=MANIFEST_COLUMNS)
        resume_report = report_from_counts(first_counts, 1)
        resume_report["unchanged"] = 1
        state = {
            "playlist_id": PLAYLIST_ID,
            "playlist_name": PLAYLIST_NAME,
            "in_progress_snapshot": SNAPSHOT_ID,
            "captured_at": CAPTURED_AT,
            "next_offset": 1,
            "expected_total": 2,
            "report": resume_report,
        }
        second_artifact = {
            "Spotify ID": "track-2",
            "Title": "Track",
            "Artist": "Artist",
            "Album": "Album",
            "Release Date": "",
            "Duration (ms)": 1000,
            "Popularity": "",
            "Spotify URL": "https://open.spotify.com/track/track-2",
        }
        with (
            patch("archive.load_existing_collection", return_value=collection()),
            patch("archive.load_checkpoint", return_value=collection()),
            patch("archive.load_manifest", return_value=pd.DataFrame(
                columns=MANIFEST_COLUMNS
            )),
            patch("archive.load_manifest_checkpoint", return_value=checkpoint_manifest),
            patch("archive._load_state", return_value=state),
            patch("archive.connect_spotify", return_value=object()),
            patch("archive.get_playlist_summary", return_value={
                "name": PLAYLIST_NAME, "snapshot_id": SNAPSHOT_ID, "total": 2
            }),
            patch("archive.get_playlist_page_occurrences", return_value=(
                [second_artifact], None, second_counts, 1, second_rows
            )) as get_page,
            patch("archive._checkpoint"),
            patch("archive.save_collection"),
            patch("archive.save_manifest"),
            patch("archive.remove_checkpoint"),
            patch("archive.remove_manifest_checkpoint"),
            patch("archive._save_state"),
            patch("archive.tqdm"),
            redirect_stdout(StringIO()),
        ):
            archive.main()
        self.assertEqual(get_page.call_args.args[2], 1)
        self.assertEqual(get_page.call_args.args[4], 2)

    def test_changed_snapshot_rejects_old_checkpoint_and_starts_clean(self):
        _, old_counts, old_rows = classify_playlist_occurrences(
            [track("track-1")],
            1,
            PLAYLIST_ID,
            PLAYLIST_NAME,
            SNAPSHOT_ID,
            CAPTURED_AT,
            {},
        )
        new_snapshot = "snapshot-2"
        _, new_counts, new_rows = classify_playlist_occurrences(
            [track("track-1")],
            1,
            PLAYLIST_ID,
            PLAYLIST_NAME,
            new_snapshot,
            CAPTURED_AT,
            {},
        )
        state = {
            "playlist_id": PLAYLIST_ID,
            "playlist_name": PLAYLIST_NAME,
            "in_progress_snapshot": SNAPSHOT_ID,
            "captured_at": CAPTURED_AT,
            "next_offset": 1,
            "expected_total": 1,
            "report": report_from_counts(old_counts, 1),
        }
        page_artifact = {
            "Spotify ID": "track-1",
            "Title": "Track",
            "Artist": "Artist",
            "Album": "Album",
            "Release Date": "",
            "Duration (ms)": 1000,
            "Popularity": "",
            "Spotify URL": "https://open.spotify.com/track/track-1",
        }
        summary = {
            "playlist_id": PLAYLIST_ID,
            "name": PLAYLIST_NAME,
            "snapshot_id": new_snapshot,
            "total": 1,
        }
        output = StringIO()
        with (
            patch("archive.load_existing_collection", return_value=collection()),
            patch("archive.load_checkpoint", return_value=collection()),
            patch("archive.load_manifest", return_value=pd.DataFrame(
                columns=MANIFEST_COLUMNS
            )),
            patch(
                "archive.load_manifest_checkpoint",
                return_value=pd.DataFrame(old_rows, columns=MANIFEST_COLUMNS),
            ),
            patch("archive._load_state", return_value=state),
            patch("archive.connect_spotify", return_value=object()),
            patch("archive.get_playlist_summary", side_effect=[summary, summary]),
            patch("archive.get_playlist_page_occurrences", return_value=(
                [page_artifact], None, new_counts, 1, new_rows
            )) as get_page,
            patch("archive._checkpoint"),
            patch("archive.save_collection"),
            patch("archive.save_manifest"),
            patch("archive.remove_checkpoint"),
            patch("archive.remove_manifest_checkpoint"),
            patch("archive._save_state"),
            patch("archive.tqdm"),
            redirect_stdout(output),
        ):
            archive.main()
        self.assertEqual(get_page.call_args.args[2], 0)
        self.assertEqual(get_page.call_args.args[4], 1)
        self.assertIn("Starting a fresh scan", output.getvalue())


if __name__ == "__main__":
    unittest.main()
