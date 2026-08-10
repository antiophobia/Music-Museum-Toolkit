"""End-to-end synthetic Museum pipeline and corruption-safety tests."""

import json
import os
import sys
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import main as application
import exhibit_manager
import inspection_manager
import listening_archive
import museum
import museum_import
from _test_support import synthetic_workspace
from collection_manager import COLLECTION_COLUMNS


def collection(extra=None):
    rows = [
        {"Museum ID": "MMT-000001", "Source": "Spotify", "Source Track ID": "one", "Title": "Gym Class", "Artist": "Lil Peep", "Album": "Single", "Duration (ms)": "180000", "Archived At": "2026-01-01", "Status": "Available"},
        {"Museum ID": "MMT-000002", "Source": "Spotify", "Source Track ID": "two", "Title": "Same Song", "Artist": "Alpha", "Album": "A", "Duration (ms)": "100000"},
        {"Museum ID": "MMT-000003", "Source": "Spotify", "Source Track ID": "three", "Title": "Same Song", "Artist": "Beta", "Album": "B", "Duration (ms)": "100000"},
    ] + list(extra or [])
    return pd.DataFrame(rows).reindex(columns=COLLECTION_COLUMNS, fill_value="")


def normalized(raw, coll=None):
    return listening_archive.normalize_event(
        raw, "synthetic", "fixture.json", "1", collection=collection() if coll is None else coll, imported_at="2026-08-01T00:00:00Z"
    )


class ApplicationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.zip_source = os.path.join(ROOT, "tests", "_application_pipeline.zip")
        self.archive = os.path.join(ROOT, "tests", "_application_pipeline.jsonl")
        self.exhibits = os.path.join(ROOT, "tests", "_application_exhibits.json")

    def tearDown(self):
        for path in (
            self.zip_source, self.archive, self.archive + ".tmp",
            self.exhibits, self.exhibits + ".tmp",
        ):
            if os.path.exists(path):
                os.remove(path)

    def test_root_menu_through_zip_inspection_and_curated_exhibit(self):
        payload = [{
            "ts": "2026-01-01T02:00:00Z",
            "spotify_track_uri": "spotify:track:one",
            "master_metadata_track_name": "Gym Class",
            "master_metadata_album_artist_name": "Lil Peep",
            "master_metadata_album_album_name": "Single",
            "ms_played": 180000,
            "reason_end": "trackdone",
        }]
        with zipfile.ZipFile(self.zip_source, "w") as archive:
            archive.writestr("account/plays.json", json.dumps(payload))
        selections = [
            "3", "7", "y", "y", "3", "gym class", "1", "10", "0",
            "2", "m", "1", "Favorite", "y", "gym class", "1", "n",
            "2", "Favorite", "3", "8", "4",
        ]
        output = StringIO()
        with (
            synthetic_workspace() as runtime_root,
            patch("museum.load_existing_collection", return_value=collection()),
            patch("museum.load_manifest", return_value=pd.DataFrame()),
            patch("museum.discover_default_archives", return_value=[self.zip_source]),
            patch("listening_archive.archive_path", return_value=self.archive),
            patch("exhibit_manager.exhibit_path", return_value=self.exhibits),
            patch("builtins.input", side_effect=selections),
            redirect_stdout(output),
        ):
            application.main(runtime_root)
        events = listening_archive.load_events(self.archive)
        exhibits = exhibit_manager.load_exhibits(self.exhibits)
        artifact = inspection_manager.search_artifacts(collection(), "gym class")[0]
        inspected = inspection_manager.inspect_artifact(artifact, events)
        curated = next(item for item in exhibits if item["type"] == "curated")
        automatic = next(
            item for item in exhibits
            if item.get("rule", {}).get("metric") == "most_played_tracks"
        )
        self.assertEqual(inspected["recorded_event_count"], 1)
        self.assertEqual(curated["artifact_ids"], ["MMT-000001"])
        self.assertEqual(
            exhibit_manager.automatic_results(automatic, events),
            [("MMT-000001", 1)],
        )
        visible = output.getvalue()
        self.assertIn("[3] Museum", visible)
        self.assertIn("Imported 1 new events", visible)
        self.assertIn("Spotify URI: spotify:track:one", visible)
        self.assertIn("FAVORITE", visible)


class ImportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.source = os.path.join(ROOT, "tests", "_spotify_export_test.json")
        self.zip_source = os.path.join(ROOT, "tests", "_spotify_export_test.zip")
        self.archive = os.path.join(ROOT, "tests", "_pipeline_archive_test.jsonl")

    def tearDown(self):
        for path in (self.source, self.zip_source, self.archive, self.archive + ".tmp"):
            if os.path.exists(path): os.remove(path)

    def test_simple_and_rich_records_scan_then_import_end_to_end(self):
        payload = [
            {"endTime": "2026-01-01 00:01", "artistName": "Lil Peep", "trackName": "Gym Class", "msPlayed": 31000},
            {"ts": "2026-01-02T03:00:00Z", "spotify_track_uri": "spotify:track:one", "master_metadata_track_name": "Gym Class", "master_metadata_album_artist_name": "Lil Peep", "master_metadata_album_album_name": "Single", "ms_played": 180000, "reason_start": "trackdone", "reason_end": "trackdone", "shuffle": True, "offline": False, "platform": "mobile", "os": "iOS", "conn_country": "US"},
            {"latency": 10, "experiment": "do-not-import"},
            {"timestamp": "2026-01-03", "latency": 11, "buffer": "diagnostic"},
            {"timestamp": "2026-01-04"},
            {"msPlayed": 20},
        ]
        with open(self.source, "w", encoding="utf-8") as output: json.dump(payload, output)
        preview = museum_import.scan_import(self.source, collection(), self.archive)
        self.assertEqual((preview["files_recognized"], preview["playback_events"], preview["malformed"]), (1, 2, 1))
        self.assertEqual((preview["events_with_uri"], preview["title_artist_only"], preview["technical_telemetry_ignored"]), (1, 1, 2))
        self.assertEqual(preview["unsupported_ignored"], 1)
        result = museum_import.commit_import(preview, collection(), self.archive, "now")
        self.assertEqual(result["added"], 2)
        events = listening_archive.load_events(self.archive)
        self.assertEqual({event["match_status"] for event in events}, {"exact_uri", "exact_title_artist"})
        rich = next(event for event in events if event["spotify_uri"])
        self.assertEqual((rich["shuffle"], rich["device_class"], rich["authority_status"]), (True, "mobile", "historical_authoritative"))

    def test_identical_and_partial_duplicate_imports_are_idempotent(self):
        raw = [{"timestamp": "2026-01-01", "spotify_uri": "spotify:track:one", "ms_played": 1}]
        first = listening_archive.import_events(raw, "synthetic", collection(), source_file="original.json", path=self.archive, imported_at="one")
        second = listening_archive.import_events(raw + [{"timestamp": "2026-01-02", "spotify_uri": "spotify:track:one", "ms_played": 2}], "synthetic", collection(), source_file="copied-export.json", path=self.archive, imported_at="two")
        self.assertEqual((first["added"], second["added"], second["already_imported"], second["total"]), (1, 1, 1, 2))

    def test_deterministic_ids_missing_fields_and_atomic_failure(self):
        raw = {"timestamp": "2026-01-01", "title": "Unknown", "artist": "Someone"}
        one = normalized(raw); two = normalized(raw)
        self.assertEqual(one["event_id"], two["event_id"])
        self.assertIsNone(one["ms_played"]); self.assertEqual(one["match_status"], "unresolved")
        listening_archive.import_events([raw], "synthetic", collection(), path=self.archive, imported_at="one")
        with open(self.archive, "rb") as source: before = source.read()
        with patch("listening_archive.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                listening_archive.import_events([{"timestamp": "2026-01-02"}], "synthetic", collection(), path=self.archive)
        with open(self.archive, "rb") as source: after = source.read()
        self.assertEqual(after, before)

    def test_zip_members_are_scanned_in_memory_and_unsafe_paths_are_rejected(self):
        payload = [{
            "ts": "2026-01-01T01:00:00Z",
            "spotify_track_uri": "spotify:track:one",
            "master_metadata_track_name": "Gym Class",
            "master_metadata_album_artist_name": "Lil Peep",
            "ms_played": 30000,
        }]
        with zipfile.ZipFile(self.zip_source, "w") as archive:
            archive.writestr("history/StreamingHistory.json", json.dumps(payload))
            archive.writestr("../unsafe.json", json.dumps(payload))
        preview = museum_import.scan_import(self.zip_source, collection(), self.archive)
        self.assertEqual(preview["playback_events"], 1)
        self.assertEqual(preview["malformed"], 1)
        self.assertEqual(preview["recognized_files"], [
            "_spotify_export_test.zip!StreamingHistory.json"
        ])
        museum_import.commit_import(preview, collection(), self.archive, "now")
        event = listening_archive.load_events(self.archive)[0]
        self.assertEqual(event["source_file"], "_spotify_export_test.zip!StreamingHistory.json")

    def test_full_zip_to_search_inspection_and_exhibits_pipeline(self):
        payload = [{
            "ts": "2026-01-01T02:00:00Z",
            "spotify_track_uri": "spotify:track:one",
            "master_metadata_track_name": "Gym Class",
            "master_metadata_album_artist_name": "Lil Peep",
            "master_metadata_album_album_name": "Single",
            "ms_played": 180000,
            "reason_end": "trackdone",
        }]
        with zipfile.ZipFile(self.zip_source, "w") as archive:
            archive.writestr("account/plays.json", json.dumps(payload))
        preview = museum_import.scan_import(self.zip_source, collection(), self.archive)
        museum_import.commit_import(preview, collection(), self.archive, "now")
        events = listening_archive.load_events(self.archive)
        artifact = inspection_manager.search_artifacts(collection(), "lil peep gym class")[0]
        inspected = inspection_manager.inspect_artifact(artifact, events)
        self.assertEqual((inspected["recorded_event_count"], inspected["completed_plays"]), (1, 1))
        exhibits = exhibit_manager.create_starter_exhibits(events)
        curated = exhibit_manager.create_exhibit(
            "Favorite Era", "curated", artifact_ids=[artifact["Museum ID"]],
            exhibits=exhibits,
        )
        exhibit_file = os.path.join(ROOT, "tests", "_pipeline_zip_exhibits.json")
        try:
            exhibit_manager.save_exhibits(exhibits + [curated], exhibit_file)
            loaded = exhibit_manager.load_exhibits(exhibit_file)
            self.assertEqual(loaded[-1]["artifact_ids"], ["MMT-000001"])
            automatic = next(item for item in loaded
                             if item.get("rule", {}).get("metric") == "most_played_tracks")
            self.assertEqual(exhibit_manager.automatic_results(automatic, events), [
                ("MMT-000001", 1)
            ])
        finally:
            if os.path.exists(exhibit_file): os.remove(exhibit_file)


class ScanProgressTests(unittest.TestCase):
    @staticmethod
    def _write_zip(path, member_name, payload):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member_name, json.dumps(payload))

    def test_multiple_archives_report_basenames_and_preserve_preview(self):
        payload = [{
            "ts": "2026-01-01T02:00:00Z",
            "spotify_track_uri": "spotify:track:one",
            "ms_played": 30000,
        }]
        with synthetic_workspace() as root:
            first = os.path.join(root, "first-export.zip")
            second = os.path.join(root, "second-export.zip")
            event_file = os.path.join(root, "events.jsonl")
            self._write_zip(first, "account/first.json", payload)
            self._write_zip(second, "account/second.json", payload)

            baseline = museum_import.scan_import(
                [first, second], collection(), event_file
            )
            emitted = []

            def progress(event, **details):
                emitted.append((event, details))

            observed = museum_import.scan_import(
                [first, second], collection(), event_file, progress=progress
            )

        self.assertEqual(observed, baseline)
        archives = [
            details for event, details in emitted if event == "archive_started"
        ]
        self.assertEqual(
            [(item["archive_index"], item["archives_total"], item["archive_name"])
             for item in archives],
            [(1, 2, "first-export.zip"), (2, 2, "second-export.zip")],
        )
        self.assertNotIn(root, json.dumps(emitted))
        self.assertEqual(
            [raw["_preview_event_id"] for _, raw in observed["candidates"]],
            [raw["_preview_event_id"] for _, raw in baseline["candidates"]],
        )

    def test_large_member_progress_is_throttled(self):
        payload = [
            {
                "ts": f"event-{index}",
                "spotify_track_uri": "spotify:track:one",
                "ms_played": 30000,
            }
            for index in range(2501)
        ]
        with synthetic_workspace() as root:
            source = os.path.join(root, "large-export.zip")
            event_file = os.path.join(root, "events.jsonl")
            self._write_zip(source, "account/RawCoreStream.json", payload)
            output = StringIO()
            with redirect_stdout(output):
                preview = museum_import.scan_import(
                    source, collection(), event_file,
                    progress=museum._print_scan_progress,
                )
            visible = output.getvalue()

        self.assertEqual(preview["playback_events"], 2501)
        self.assertEqual(visible.count("Records processed:"), 3)
        self.assertIn("Batch 1/3", visible)
        self.assertIn("Records processed: 1,000 / 2,501", visible)
        self.assertIn("Records processed: 2,000 / 2,501", visible)
        self.assertIn("Records processed: 2,501 / 2,501", visible)
        self.assertIn("Playback records found: 2,501", visible)
        self.assertNotIn(root, visible)

    def test_import_flow_shows_immediate_status_completion_and_confirmation(self):
        payload = [{
            "ts": "2026-01-01T02:00:00Z",
            "spotify_track_uri": "spotify:track:one",
            "ms_played": 30000,
        }]
        with synthetic_workspace() as root:
            source = os.path.join(root, "detected-export.zip")
            event_file = os.path.join(root, "events.jsonl")
            self._write_zip(source, "account/history.json", payload)
            answers = iter(["y", "n"])

            def answer(prompt=""):
                print(prompt, end="")
                return next(answers)

            output = StringIO()
            with (
                patch("museum.discover_default_archives", return_value=[source]),
                patch("listening_archive.archive_path", return_value=event_file),
                patch("museum.commit_import") as commit,
                patch("builtins.input", side_effect=answer),
                redirect_stdout(output),
            ):
                self.assertIsNone(museum.import_museum_data_flow(collection()))
            visible = output.getvalue()

        scan_prompt = visible.index("Scan detected archives? [Y/N]:")
        scan_status = visible.index("Scanning Spotify archives...")
        archive_status = visible.index("[1/1] detected-export.zip", scan_status)
        scan_complete = visible.index("Scan complete.")
        preview = visible.index("MUSEUM DATA IMPORT", scan_status)
        confirmation = visible.index("Proceed with permanent import? [Y/N]:")
        self.assertLess(scan_prompt, scan_status)
        self.assertLess(scan_status, archive_status)
        self.assertLess(archive_status, scan_complete)
        self.assertLess(scan_complete, preview)
        self.assertLess(preview, confirmation)
        self.assertNotIn(root, visible)
        commit.assert_not_called()

    def test_member_failure_reports_only_safe_names(self):
        with synthetic_workspace() as root:
            source = os.path.join(root, "broken-export.zip")
            event_file = os.path.join(root, "events.jsonl")
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("private/failing.json", "{not-json")
            output = StringIO()
            with redirect_stdout(output):
                preview = museum_import.scan_import(
                    source, collection(), event_file,
                    progress=museum._print_scan_progress,
                )
            visible = output.getvalue()

        self.assertEqual((preview["playback_events"], preview["malformed"]), (0, 1))
        self.assertIn("Could not scan member safely: failing.json", visible)
        self.assertNotIn("private/failing.json", visible)
        self.assertNotIn(root, visible)


class IdentityAndClassificationTests(unittest.TestCase):
    def test_exact_uri_title_artist_ambiguous_and_no_fuzzy_mutation(self):
        duplicate = {"Museum ID": "MMT-000004", "Source": "Spotify", "Source Track ID": "four", "Title": "Gym Class", "Artist": "Lil Peep", "Album": "Other"}
        coll = collection([duplicate])
        self.assertEqual(normalized({"timestamp": "1", "spotify_uri": "spotify:track:one"}, coll)["museum_id"], "MMT-000001")
        ambiguous = normalized({"timestamp": "2", "title": "Gym Class", "artist": "Lil Peep"}, coll)
        self.assertEqual((ambiguous["match_status"], ambiguous["museum_id"]), ("ambiguous", ""))
        fuzzy = normalized({"timestamp": "3", "title": "Gim Clas", "artist": "Lil Peep"}, coll)
        self.assertEqual((fuzzy["match_status"], fuzzy["museum_id"]), ("unresolved", ""))

    def test_classification_precedence_and_duration_rule(self):
        cases = [
            ({"ms_played": 30000}, None, "meaningful_play"),
            ({"ms_played": 29999}, None, "short_play"),
            ({"ms_played": 1000, "end_reason": "forward button"}, None, "explicit_skip"),
            ({"ms_played": 1000, "end_reason": "track completed"}, None, "completed_play"),
            ({"ms_played": 90000}, 100000, "completed_play"),
            ({"ms_played": 1000, "end_reason": "remote"}, None, "interrupted_or_other"),
            ({"ms_played": None, "end_reason": "logout"}, None, "interrupted_or_other"),
        ]
        for event, duration, expected in cases:
            self.assertEqual(listening_archive.classify_playback(event, duration), expected)


class SearchInspectionTests(unittest.TestCase):
    def test_search_all_supported_modes_including_fuzzy_selection(self):
        coll = collection()
        for query in ("Gym Class", "Lil Peep Gym Class", "Lil Peep", "Single", "spotify:track:one", "MMT-000001", "gYm cLaSs", "Gim Clas"):
            with self.subTest(query=query): self.assertEqual(inspection_manager.search_artifacts(coll, query)[0]["Museum ID"], "MMT-000001")
        self.assertEqual(len(inspection_manager.search_artifacts(coll, "Same Song")), 2)

    def test_artifact_artist_album_rich_and_sparse_aggregation(self):
        events = [
            normalized({"timestamp": "2025-01-01T01:00:00Z", "spotify_uri": "spotify:track:one", "ms_played": 180000, "end_reason": "track completed", "shuffle": True, "device": "mobile"}),
            normalized({"timestamp": "2026-02-01T22:00:00Z", "spotify_uri": "spotify:track:one", "ms_played": 1000, "end_reason": "remote"}),
        ]
        artifact = collection().iloc[0].to_dict(); result = inspection_manager.inspect_artifact(artifact, events)
        self.assertEqual(
            (result["recorded_event_count"], result["completed_plays"],
             result["short_plays"], result["interrupted_other"]),
            (2, 1, 0, 1),
        )
        self.assertEqual(result["activity_by_year"], {"2025": 1, "2026": 1}); self.assertIn("mobile", result["devices"])
        artist = inspection_manager.inspect_artist(collection(), events, "Lil Peep")
        album = inspection_manager.inspect_album(collection(), events, "Single")
        self.assertEqual((len(artist["artifacts"]), album["recorded_event_count"]), (1, 2))
        sparse = inspection_manager.inspect_artifact(collection().iloc[1].to_dict(), [])
        self.assertIsNone(sparse["average_listening_ms"]); self.assertEqual(sparse["recorded_event_count"], 0)

    def test_artifact_terminal_inspection_shows_supported_sections(self):
        event = normalized({
            "timestamp": "2026-02-01T22:00:00Z",
            "spotify_uri": "spotify:track:one",
            "ms_played": 180000,
            "reason_start": "trackdone",
            "reason_end": "trackdone",
            "shuffle": True,
            "offline": False,
            "device": "mobile",
            "os": "iOS",
            "country": "US",
        })
        manifest = pd.DataFrame([{
            "Museum ID": "MMT-000001", "Playlist Position": "7",
            "Classification": "valid track", "Added At": "2025-12-01",
        }])
        output = StringIO()
        with patch(
            "museum._select_artifact", return_value=collection().iloc[0].to_dict()
        ), redirect_stdout(output):
            museum.inspect_artifact_flow(collection(), [event], manifest)
        visible = output.getvalue()
        for expected in (
            "MUSEUM RECORD", "Spotify URI: spotify:track:one",
            "Duration: 3m 0s", "Preserved at: 2026-01-01",
            "PLAYBACK SUMMARY", "ACTIVITY", "By year: 2026: 1",
            "LISTENING CONTEXT", "Device/platform: mobile: 1",
            "Operating system: iOS: 1", "Shuffle: true: 1",
            "PLAYLIST OCCURRENCE HISTORY", "Position 7: valid track",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, visible)

    def test_missing_durations_do_not_become_zero_and_album_artist_disambiguates(self):
        events = [normalized({
            "timestamp": "2026-01-01", "spotify_uri": "spotify:track:one",
            "end_reason": "track completed",
        })]
        result = inspection_manager.inspect_artifact(collection().iloc[0].to_dict(), events)
        self.assertIsNone(result["total_listening_ms"])
        self.assertIsNone(result["average_listening_ms"])
        self.assertEqual(result["meaningful_plays"], 0)
        extra = {"Museum ID": "MMT-000004", "Source": "Spotify",
                 "Source Track ID": "four", "Title": "Other",
                 "Artist": "Other Artist", "Album": "Single"}
        albums = inspection_manager.search_albums(collection([extra]), "Single")
        self.assertEqual(
            {(item["album"], item["artist"]) for item in albums},
            {("Single", "Lil Peep"), ("Single", "Other Artist")},
        )


class ExhibitFoundationTests(unittest.TestCase):
    def setUp(self): self.path = os.path.join(ROOT, "tests", "_pipeline_exhibits_test.json")
    def tearDown(self):
        for path in (self.path, self.path + ".tmp"):
            if os.path.exists(path): os.remove(path)

    def test_stable_identity_curated_membership_reorder_and_dependencies(self):
        curated = exhibit_manager.create_exhibit("Era", "curated")
        curated = exhibit_manager.add_curated_artifact(curated, "MMT-000001")
        automatic = exhibit_manager.create_exhibit("Years", "automatic", rule={"metric": "listening_by_year"}, exhibits=[curated])
        reordered = exhibit_manager.reorder_exhibits([curated, automatic], [automatic["exhibit_id"], curated["exhibit_id"]])
        self.assertEqual(reordered[1]["exhibit_id"], curated["exhibit_id"])
        self.assertEqual(reordered[1]["artifact_ids"], ["MMT-000001"])
        self.assertIn("event_timestamp", automatic["dependencies"])
        self.assertEqual(exhibit_manager.affected_exhibits([automatic], ["event_timestamp"]), [automatic])
        exhibit_manager.save_exhibits(reordered, self.path)
        self.assertEqual(exhibit_manager.load_exhibits(self.path)[1]["artifact_ids"], ["MMT-000001"])

    def test_generated_artist_and_starters_recalculate_without_curated_overwrite(self):
        events = [normalized({"timestamp": "2026-01-01T02:00:00Z", "spotify_uri": "spotify:track:one", "ms_played": 30000})]
        generated = exhibit_manager.create_exhibit("Lil Peep", "generated", artist="Lil Peep")
        self.assertEqual(exhibit_manager.generated_artist_results(generated, collection(), events)["recorded_event_count"], 1)
        curated = exhibit_manager.create_exhibit("Keep", "curated", artifact_ids=["MMT-000002"])
        starters = exhibit_manager.create_starter_exhibits(events, [curated])
        self.assertEqual(starters[0]["artifact_ids"], ["MMT-000002"])
        self.assertGreaterEqual(len(starters), 4)
        track = next(item for item in starters if item.get("rule", {}).get("metric") == "most_played_tracks")
        self.assertEqual(exhibit_manager.automatic_results(track, events), [("MMT-000001", 1)])

    def test_invalid_file_and_atomic_failure_preserve_prior_data(self):
        valid = exhibit_manager.create_exhibit("Keep", "curated")
        exhibit_manager.save_exhibits([valid], self.path)
        with open(self.path, "rb") as source: before = source.read()
        with patch("exhibit_manager.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError): exhibit_manager.save_exhibits([valid], self.path)
        with open(self.path, "rb") as source: after = source.read()
        self.assertEqual(after, before)
        with open(self.path, "w", encoding="utf-8") as output: output.write("{}")
        with self.assertRaises(ValueError): exhibit_manager.load_exhibits(self.path)
        with open(self.path, "w", encoding="utf-8") as output: output.write("[1]")
        with self.assertRaises(ValueError): exhibit_manager.load_exhibits(self.path)


class MuseumMenuTests(unittest.TestCase):
    def test_return_invalid_and_interruption_are_resilient(self):
        with patch("museum.load_existing_collection", return_value=collection()), patch("museum.load_events", return_value=[]), patch("museum.load_exhibits", return_value=[]), patch("museum.load_manifest", return_value=pd.DataFrame()), patch("builtins.input", side_effect=["invalid", "8"]):
            museum.main()
        with patch("museum.load_existing_collection", return_value=collection()), patch("museum.load_events", return_value=[]), patch("museum.load_exhibits", return_value=[]), patch("museum.load_manifest", return_value=pd.DataFrame()), patch("builtins.input", side_effect=KeyboardInterrupt):
            museum.main()

    def test_import_preview_requires_confirmation(self):
        preview = {key: 0 for key in (
            "files_recognized", "events_with_uri", "title_artist_only", "exact_title_artist",
            "ambiguous", "unresolved", "malformed", "already_imported",
            "technical_telemetry_ignored"
        )}
        preview.update({"playback_events": 1, "candidates": [("x.json", {"timestamp": "1"})]})
        with patch("museum.discover_default_archives", return_value=[]), patch(
            "museum.scan_import", return_value=preview
        ), patch("museum.commit_import") as commit, patch(
            "builtins.input", side_effect=["export.json", "n"]
        ):
            self.assertIsNone(museum.import_museum_data_flow(collection()))
        commit.assert_not_called()

    def test_detected_zip_archives_are_offered_before_manual_path(self):
        preview = {key: 0 for key in (
            "files_recognized", "events_with_uri", "title_artist_only",
            "exact_title_artist", "ambiguous", "unresolved", "malformed",
            "already_imported", "technical_telemetry_ignored",
        )}
        preview.update({"playback_events": 1, "candidates": []})
        archives = [r"C:\Input\Spotify Data\account.zip"]
        with (
            patch("museum.discover_default_archives", return_value=archives),
            patch("museum.scan_import", return_value=preview) as scan,
            patch("museum.commit_import") as commit,
            patch("builtins.input", side_effect=["y", "n"]),
        ):
            self.assertIsNone(museum.import_museum_data_flow(collection()))
        scan.assert_called_once()
        self.assertEqual(scan.call_args.args[0], archives)
        self.assertIsInstance(scan.call_args.args[1], pd.DataFrame)
        self.assertIs(scan.call_args.kwargs["progress"], museum._print_scan_progress)
        commit.assert_not_called()

    def test_import_menu_dispatch_refreshes_supported_starters(self):
        with (
            patch("museum.load_existing_collection", return_value=collection()),
            patch("museum.load_events", side_effect=[[], []]),
            patch("museum.load_exhibits", return_value=[]),
            patch("museum.load_manifest", return_value=pd.DataFrame()),
            patch("museum.import_museum_data_flow", return_value={"added": 1}) as import_flow,
            patch("museum.create_starter_exhibits", return_value=[]) as starters,
            patch("museum.save_exhibits"),
            patch("builtins.input", side_effect=["7", "8"]),
        ):
            museum.main()
        import_flow.assert_called_once()
        starters.assert_called_once()
        self.assertEqual(starters.call_args.args[:2], ([], []))
        self.assertIsInstance(starters.call_args.args[2], pd.DataFrame)
        self.assertIsInstance(starters.call_args.args[3], pd.DataFrame)

    def test_curated_remove_and_exhibit_reorder_are_wired_to_cli(self):
        curated = exhibit_manager.create_exhibit(
            "Curated", "curated", artifact_ids=["MMT-000001"]
        )
        with patch("museum.save_exhibits") as save, patch(
            "builtins.input", side_effect=["1", "2", "1"]
        ):
            result = museum._browse_exhibits(collection(), [], [curated])
        self.assertEqual(result[0]["artifact_ids"], [])
        save.assert_called_once()
        automatic = exhibit_manager.create_exhibit(
            "Years", "automatic", rule={"metric": "listening_by_year"},
            exhibits=[curated],
        )
        with patch("museum.save_exhibits") as save, patch(
            "builtins.input", return_value="2,1"
        ):
            reordered = museum._reorder_exhibits([curated, automatic])
        self.assertEqual(reordered[0]["exhibit_id"], automatic["exhibit_id"])
        save.assert_called_once()


if __name__ == "__main__": unittest.main()
