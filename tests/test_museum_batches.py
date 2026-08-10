"""Synthetic scale, batching, indexing, and atomicity tests for Museum import."""

import json
import os
import sys
import unittest
import zipfile
from unittest.mock import patch

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import listening_archive
import museum_import
from _test_support import synthetic_workspace
from collection_manager import COLLECTION_COLUMNS


def make_collection(size=1):
    rows = [{
        "Museum ID": f"MMT-{index + 1:06d}",
        "Source": "Spotify",
        "Source Track ID": f"track-{index}",
        "Title": f"Song {index}",
        "Artist": f"Artist {index}",
    } for index in range(size)]
    return pd.DataFrame(rows).reindex(columns=COLLECTION_COLUMNS, fill_value="")


def identity_collection():
    rows = [
        {
            "Museum ID": "MMT-000001", "Source": "Spotify",
            "Source Track ID": "known", "Title": "Known", "Artist": "Artist",
        },
        {
            "Museum ID": "MMT-000002", "Source": "Spotify",
            "Source Track ID": "duplicate-a", "Title": "Duplicate", "Artist": "Artist",
        },
        {
            "Museum ID": "MMT-000003", "Source": "Spotify",
            "Source Track ID": "duplicate-b", "Title": "Duplicate", "Artist": "Artist",
        },
    ]
    return pd.DataFrame(rows).reindex(columns=COLLECTION_COLUMNS, fill_value="")


def account_records(count, modes=False):
    records = []
    for index in range(count):
        title, artist = "Song 0", "Artist 0"
        if modes:
            title, artist = (
                ("Known", "Artist") if index % 3 == 0 else
                ("Duplicate", "Artist") if index % 3 == 1 else
                ("Missing", "Nobody")
            )
        records.append({
            "endTime": f"account-{index}",
            "artistName": artist,
            "trackName": title,
            "msPlayed": 30000,
        })
    return records


def rich_records(count):
    return [{
        "timestamp_utc": f"rich-{index}",
        "message_content_uri": "spotify:track:track-0",
        "message_ms_played": 30000,
        "message_reason_start": "trackdone",
        "message_reason_end": "trackdone",
        "message_shuffle": bool(index % 2),
        "message_content_is_downloaded": not bool(index % 2),
        "context_device_type": "mobile",
        "context_os_name": "synthetic-os",
        "context_conn_country": "ZZ",
        "message_social_listening": bool(index % 2),
        "message_context_uri": "spotify:playlist:synthetic",
    } for index in range(count)]


def write_zip(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for member_name, payload in members.items():
            archive.writestr(member_name, json.dumps(payload))


class BatchBoundaryTests(unittest.TestCase):
    def test_default_boundaries_partial_batch_and_empty_input(self):
        cases = ((0, 0), (1000, 1), (1001, 2), (10000, 10), (10397, 11))
        for record_count, expected_batches in cases:
            with self.subTest(record_count=record_count):
                batches = list(listening_archive.iter_record_batches(
                    list(range(record_count))
                ))
                self.assertEqual(len(batches), expected_batches)
                self.assertEqual(
                    [item.batch_number for item in batches],
                    list(range(1, expected_batches + 1)),
                )
                if batches:
                    self.assertEqual(batches[-1].end_offset, record_count)
                    self.assertLessEqual(len(batches[-1].records), 1000)

    def test_custom_batch_size_changes_boundaries_not_record_order(self):
        records = list(range(10397))
        for batch_size in (1, 333, 1000, 4096):
            batches = list(listening_archive.iter_record_batches(records, batch_size))
            flattened = [record for batch in batches for record in batch.records]
            self.assertEqual(flattened, records)
        with self.assertRaises(ValueError):
            list(listening_archive.iter_record_batches(records, 0))


class BatchScaleTests(unittest.TestCase):
    def test_10000_account_records_and_cross_batch_identity_counts(self):
        emitted = []
        with synthetic_workspace() as root:
            source = os.path.join(root, "account.zip")
            event_file = os.path.join(root, "events.jsonl")
            write_zip(source, {
                "StreamingHistory_music_0.json": account_records(10000, modes=True)
            })
            preview = museum_import.scan_import(
                source, identity_collection(), event_file,
                progress=lambda event, **details: emitted.append((event, details)),
            )

        batches = [details for event, details in emitted if event == "batch_complete"]
        self.assertEqual(len(batches), 10)
        self.assertEqual(batches[-1]["records_processed"], 10000)
        self.assertEqual(batches[-1]["playback_records_found"], 10000)
        self.assertEqual(
            (preview["playback_events"], preview["title_artist_only"],
             preview["rich_playback"], preview["resolved"],
             preview["unresolved"], preview["ambiguous"]),
            (10000, 10000, 0, 3334, 3333, 3333),
        )

    def test_10397_rich_records_use_actual_schema_and_partial_batch(self):
        emitted = []
        with synthetic_workspace() as root:
            source = os.path.join(root, "technical.zip")
            event_file = os.path.join(root, "events.jsonl")
            write_zip(source, {"RawCoreStream.json": rich_records(10397)})
            preview = museum_import.scan_import(
                source, make_collection(), event_file,
                progress=lambda event, **details: emitted.append((event, details)),
            )

        batches = [details for event, details in emitted if event == "batch_complete"]
        first = preview["candidates"][0][1]
        self.assertEqual(len(batches), 11)
        self.assertEqual(
            (batches[-1]["batch_number"], batches[-1]["records_processed"]),
            (11, 10397),
        )
        self.assertEqual(
            (preview["playback_events"], preview["rich_playback"],
             preview["events_with_uri"], preview["resolved"]),
            (10397, 10397, 10397, 10397),
        )
        self.assertEqual(
            (first["spotify_uri"], first["ms_played"], first["start_reason"],
             first["end_reason"], first["device_class"], first["os"],
             first["country"], first["social_listening"],
             first["session_context"]),
            ("spotify:track:track-0", 30000, "trackdone", "trackdone",
             "mobile", "synthetic-os", "ZZ", False,
             "spotify:playlist:synthetic"),
        )

    def test_more_than_20000_records_across_multiple_members(self):
        emitted = []
        with synthetic_workspace() as root:
            source = os.path.join(root, "combined.zip")
            event_file = os.path.join(root, "events.jsonl")
            write_zip(source, {
                "StreamingHistory_music_0.json": account_records(10000),
                "StreamingHistory_music_1.json": account_records(10001),
            })
            preview = museum_import.scan_import(
                source, make_collection(), event_file,
                progress=lambda event, **details: emitted.append((event, details)),
            )

        batches = [details for event, details in emitted if event == "batch_complete"]
        self.assertEqual(preview["playback_events"], 20001)
        self.assertEqual(preview["files_recognized"], 2)
        self.assertEqual(len(batches), 21)
        self.assertEqual(batches[-1]["records_processed"], 10001)

    def test_hundreds_of_telemetry_members_skip_normalization(self):
        members = {
            f"technical/telemetry-{index}.json": [
                {"latency": index, "buffer": "synthetic"} for _ in range(4)
            ]
            for index in range(250)
        }
        members["history/StreamingHistory_music_0.json"] = account_records(1001)
        with synthetic_workspace() as root:
            source = os.path.join(root, "mixed.zip")
            event_file = os.path.join(root, "events.jsonl")
            write_zip(source, members)
            with patch(
                "museum_import.normalize_event", wraps=museum_import.normalize_event
            ) as normalize:
                preview = museum_import.scan_import(
                    source, make_collection(), event_file
                )

        self.assertEqual(preview["playback_events"], 1001)
        self.assertEqual(preview["technical_telemetry_ignored"], 1000)
        self.assertEqual(preview["files_recognized"], 1)
        self.assertEqual(normalize.call_count, 1001)


class BatchSafetyTests(unittest.TestCase):
    def test_collection_indexes_are_built_once_for_preview_and_commit(self):
        collection = make_collection(1280)
        with synthetic_workspace() as root:
            source = os.path.join(root, "account.zip")
            event_file = os.path.join(root, "events.jsonl")
            write_zip(source, {
                "StreamingHistory_music_0.json": account_records(2000)
            })
            with patch(
                "museum_import.build_collection_identity_indexes",
                wraps=listening_archive.build_collection_identity_indexes,
            ) as preview_indexes:
                preview = museum_import.scan_import(
                    source, collection, event_file
                )
            self.assertEqual(preview_indexes.call_count, 1)
            with patch(
                "listening_archive.build_collection_identity_indexes",
                wraps=listening_archive.build_collection_identity_indexes,
            ) as commit_indexes:
                result = museum_import.commit_import(
                    preview, collection, event_file, "now"
                )
            self.assertEqual(commit_indexes.call_count, 1)

        self.assertEqual((result["added"], result["total"]), (2000, 2000))

    def test_batch_size_does_not_change_event_ids_and_repeat_is_idempotent(self):
        with synthetic_workspace() as root:
            source = os.path.join(root, "rich.zip")
            event_file = os.path.join(root, "events.jsonl")
            write_zip(source, {"RawCoreStream.json": rich_records(1001)})
            small = museum_import.scan_import(
                source, make_collection(), event_file, batch_size=17
            )
            default = museum_import.scan_import(
                source, make_collection(), event_file, batch_size=1000
            )
            self.assertFalse(os.path.exists(event_file))
            self.assertEqual(small, default)
            first = museum_import.commit_import(
                small, make_collection(), event_file, "one", batch_size=17
            )
            second = museum_import.commit_import(
                default, make_collection(), event_file, "two", batch_size=1000
            )

        self.assertEqual((first["added"], second["added"]), (1001, 0))
        self.assertEqual(second["already_imported"], 1001)

    def test_malformed_record_inside_batch_does_not_abort_preview(self):
        records = account_records(1001)
        records[999] = {"trackName": "Missing Timestamp", "msPlayed": 10}
        emitted = []
        with synthetic_workspace() as root:
            source = os.path.join(root, "account.zip")
            event_file = os.path.join(root, "events.jsonl")
            write_zip(source, {"StreamingHistory_music_0.json": records})
            preview = museum_import.scan_import(
                source, make_collection(), event_file,
                progress=lambda event, **details: emitted.append((event, details)),
            )

        batches = [details for event, details in emitted if event == "batch_complete"]
        self.assertEqual((preview["playback_events"], preview["malformed"]), (1000, 1))
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[-1]["records_processed"], 1001)

    def test_failed_later_permanent_batch_leaves_archive_unchanged(self):
        with synthetic_workspace() as root:
            event_file = os.path.join(root, "events.jsonl")
            listening_archive.import_events(
                [{"timestamp": "seed", "spotify_uri": "spotify:track:track-0"}],
                "synthetic", make_collection(), path=event_file, imported_at="seed",
            )
            with open(event_file, "rb") as source:
                before = source.read()
            preview = {"candidates": [
                ("valid.json", {
                    "event_timestamp": "valid", "spotify_uri": "spotify:track:track-0",
                    "source_record_id": "valid",
                }),
                ("invalid.json", {
                    "event_timestamp": "invalid", "spotify_uri": "spotify:track:track-0",
                    "ms_played": -1, "source_record_id": "invalid",
                }),
            ]}
            with self.assertRaises(ValueError):
                museum_import.commit_import(
                    preview, make_collection(), event_file, "attempt", batch_size=1
                )
            with open(event_file, "rb") as source:
                after = source.read()

        self.assertEqual(after, before)
        self.assertFalse(os.path.exists(event_file + ".tmp"))

    def test_version_two_archive_upgrade_preserves_event_id(self):
        event = listening_archive.normalize_event(
            {"timestamp": "legacy", "spotify_uri": "spotify:track:track-0"},
            "synthetic", imported_at="then", collection=make_collection(),
        )
        event_id = event["event_id"]
        event["archive_version"] = "2"
        event.pop("social_listening")
        event.pop("session_context")
        with synthetic_workspace() as root:
            event_file = os.path.join(root, "events.jsonl")
            with open(event_file, "w", encoding="utf-8") as output:
                output.write(json.dumps(event, sort_keys=True) + "\n")
            upgraded = listening_archive.load_events(event_file)[0]

        self.assertEqual(upgraded["event_id"], event_id)
        self.assertEqual(upgraded["archive_version"], listening_archive.ARCHIVE_VERSION)
        self.assertIsNone(upgraded["social_listening"])
        self.assertEqual(upgraded["session_context"], "")


if __name__ == "__main__":
    unittest.main()
