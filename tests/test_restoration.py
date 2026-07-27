"""Offline regression tests for playlist restoration v1."""

import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, Mock, mock_open, patch

import pandas as pd
from requests import RequestException


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import restoration_manager
import restore_playlist
import spotify_api
from collection_manager import COLLECTION_COLUMNS
from manifest_manager import MANIFEST_COLUMNS


PLAYLIST_ID = "source-playlist"
PLAYLIST_NAME = "Preserved Playlist"
SNAPSHOT_ID = "snapshot-complete"
CAPTURED_AT = "2026-07-26T19:00:00+00:00"


def preservation_fixture(unique_tracks=1271):
    collection_rows = []
    manifest_rows = []
    for index in range(1, unique_tracks + 1):
        track_id = f"track-{index}"
        museum_id = f"MMT-{index:06}"
        collection_rows.append({
            "Museum ID": museum_id,
            "Source": "Spotify",
            "Source Track ID": track_id,
            "Title": f"Track {index}",
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
        manifest_rows.append(manifest_row(
            index, "valid track", track_id, museum_id
        ))

    position = unique_tracks + 1
    for source_position in (1, 2, 3):
        track_id = f"track-{source_position}"
        museum_id = f"MMT-{source_position:06}"
        manifest_rows.append(manifest_row(
            position,
            "duplicate occurrence",
            track_id,
            museum_id,
            duplicate_of=source_position,
        ))
        position += 1
    for classification, count in (
        ("local file", 3),
        ("unavailable entry", 3),
        ("unsupported entry", 2),
    ):
        for _ in range(count):
            manifest_rows.append(manifest_row(position, classification))
            position += 1

    collection = pd.DataFrame(collection_rows, columns=COLLECTION_COLUMNS)
    manifest = pd.DataFrame(manifest_rows, columns=MANIFEST_COLUMNS)
    counts = manifest["Classification"].value_counts().to_dict()
    sync_state = {
        "playlist_id": PLAYLIST_ID,
        "playlist_name": PLAYLIST_NAME,
        "complete_snapshot": SNAPSHOT_ID,
        "playlist_total": len(manifest),
        "last_report": {
            "playlist_items_reported": len(manifest),
            "playlist_entries_scanned": len(manifest),
            "new_artifacts": 0,
            "metadata_updates": 0,
            "unchanged": unique_tracks,
            "valid_tracks": counts.get("valid track", 0),
            "duplicate_tracks": counts.get("duplicate occurrence", 0),
            "local_files": counts.get("local file", 0),
            "unavailable_entries": counts.get("unavailable entry", 0),
            "unsupported_entries": counts.get("unsupported entry", 0),
            "malformed_entries": counts.get("malformed entry", 0),
        },
    }
    return collection, manifest, sync_state


def manifest_row(
    position,
    classification,
    track_id="",
    museum_id="",
    duplicate_of="",
):
    restorable = classification in {"valid track", "duplicate occurrence"}
    return {
        "Manifest Version": "1",
        "Playlist ID": PLAYLIST_ID,
        "Playlist Name": PLAYLIST_NAME,
        "Snapshot ID": SNAPSHOT_ID,
        "Captured At": CAPTURED_AT,
        "Playlist Position": str(position),
        "Classification": classification,
        "Restorable": "True" if restorable else "False",
        "Museum ID": museum_id,
        "Source Track ID": track_id,
        "Spotify URI": f"spotify:track:{track_id}" if track_id else "",
        "Title": f"Track {position}" if track_id else "",
        "Artist": "Artist" if track_id else "",
        "Album": "Album" if track_id else "",
        "Added At": "",
        "Duplicate Of Position": str(duplicate_of) if duplicate_of else "",
        "Reason": "" if restorable else f"{classification} cannot be restored.",
    }


def small_plan():
    collection, manifest, state = preservation_fixture(unique_tracks=3)
    return restoration_manager.build_restoration_plan(collection, manifest, state)


def destination(
    uris,
    public=False,
    snapshot="dest-snapshot",
    playlist_id="destination",
    name="Restored",
    owner="owner",
    collaborative=False,
    description="Restored by Music Museum Toolkit. Restoration run: run-1",
):
    return {
        "playlist_id": playlist_id,
        "name": name,
        "owner_id": owner,
        "public": public,
        "collaborative": collaborative,
        "description": description,
        "snapshot_id": snapshot,
        "url": f"https://open.spotify.com/playlist/{playlist_id}",
        "uris": list(uris),
    }


def restoration_state(uris):
    return {
        "run_id": "run-1",
        "planned_uris": list(uris),
        "destination_playlist_id": "destination",
        "destination_playlist_url": "https://open.spotify.com/playlist/destination",
        "destination_playlist_name": "Restored",
        "destination_visibility": "private",
        "destination_owner_id": "owner",
        "last_confirmed_destination_length": 0,
        "last_returned_destination_snapshot_id": "",
        "report_path": "report.csv",
        "status": "created",
    }


def spotify_playlist_details(
    total,
    snapshot="stable-snapshot",
    name="Restored",
    owner="owner",
    public=False,
    collaborative=False,
    description="Restored by Music Museum Toolkit. Restoration run: run-1",
):
    return {
        "id": "destination",
        "name": name,
        "owner": {"id": owner},
        "public": public,
        "collaborative": collaborative,
        "description": description,
        "snapshot_id": snapshot,
        "external_urls": {
            "spotify": "https://open.spotify.com/playlist/destination"
        },
        "items": {"total": total},
    }


def visibility_bundle(public=False):
    plan = small_plan()
    state = restoration_manager.create_initial_state(
        plan,
        "run-1",
        "Restored",
        public,
        restoration_manager.report_path_for_run("run-1"),
    )
    state.update({
        "destination_playlist_id": "destination",
        "destination_playlist_url": (
            "https://open.spotify.com/playlist/destination"
        ),
        "destination_owner_id": "owner",
        "last_returned_destination_snapshot_id": "created-snapshot",
        "status": "created",
    })
    report = restoration_manager.build_report(plan, "run-1")
    restoration_manager.update_report(report, state)
    return plan, state, report


class RestorationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collection, cls.manifest, cls.sync_state = preservation_fixture()
        cls.plan = restoration_manager.build_restoration_plan(
            cls.collection, cls.manifest, cls.sync_state
        )

    def test_verified_shape_builds_exact_1274_item_plan(self):
        self.assertEqual(self.plan["manifest_occurrences"], 1282)
        self.assertEqual(self.plan["ready_count"], 1274)
        self.assertEqual(self.plan["excluded_count"], 8)
        self.assertEqual(self.plan["batch_count"], 13)

    def test_duplicate_occurrences_retain_exact_order(self):
        self.assertEqual(
            self.plan["uris"][-3:],
            [
                "spotify:track:track-1",
                "spotify:track:track-2",
                "spotify:track:track-3",
            ],
        )
        report = restoration_manager.build_report(self.plan, "run")
        duplicate_rows = [
            row for row in report
            if row["Classification"] == "duplicate occurrence"
        ]
        self.assertEqual(len(duplicate_rows), 3)
        self.assertEqual(
            [row["Destination Position"] for row in duplicate_rows],
            ["1272", "1273", "1274"],
        )
        state = restoration_state(self.plan["uris"])
        state["last_confirmed_destination_length"] = 1274
        restoration_manager.update_report(report, state)
        self.assertTrue(all(row["Result"] == "Added" for row in duplicate_rows))

    def test_nonrestorable_rows_are_reported_and_never_planned(self):
        report = restoration_manager.build_report(self.plan, "run")
        excluded = [row for row in report if row["Result"] == "Not included"]
        self.assertEqual(len(excluded), 8)
        self.assertEqual(
            {row["Classification"] for row in excluded},
            {"local file", "unavailable entry", "unsupported entry"},
        )
        self.assertTrue(all(row["Reason"] for row in excluded))

    def test_invalid_snapshot_and_stored_identity_are_refused(self):
        bad_state = dict(self.sync_state, complete_snapshot="other")
        with self.assertRaises(ValueError):
            restoration_manager.build_restoration_plan(
                self.collection, self.manifest, bad_state
            )
        bad_manifest = self.manifest.copy()
        bad_manifest.loc[0, "Spotify URI"] = "spotify:track:replacement"
        with self.assertRaises(ValueError):
            restoration_manager.build_restoration_plan(
                self.collection, bad_manifest, self.sync_state
            )

    def test_batches_never_exceed_100_and_preserve_order(self):
        groups = list(restoration_manager.batches(self.plan["uris"]))
        self.assertEqual(len(groups), 13)
        self.assertTrue(all(len(group) <= 100 for group in groups))
        self.assertEqual(
            [uri for group in groups for uri in group], self.plan["uris"]
        )


class RestorationPersistenceTests(unittest.TestCase):
    def test_state_and_report_use_atomic_replacement(self):
        state = {"status": "planned"}
        with (
            patch("restoration_manager.os.makedirs"),
            patch("builtins.open", mock_open()),
            patch("restoration_manager.os.replace") as replace,
        ):
            restoration_manager._atomic_json(state, "state.json")
        replace.assert_called_once_with("state.json.tmp", "state.json")

        report = [{column: "" for column in restoration_manager.REPORT_COLUMNS}]
        writer = MagicMock()
        with (
            patch("restoration_manager.os.makedirs"),
            patch("builtins.open", mock_open()),
            patch("restoration_manager.csv.DictWriter", return_value=writer),
            patch("restoration_manager.os.replace") as replace,
        ):
            restoration_manager.save_report(report, "reports/run.csv")
        writer.writeheader.assert_called_once()
        writer.writerows.assert_called_once_with(report)
        replace.assert_called_once_with("reports/run.csv.tmp", "reports/run.csv")

    def test_creation_response_is_immediately_persisted(self):
        state = restoration_state([])
        state.update({
            "destination_playlist_id": "",
            "destination_visibility": "private",
            "destination_playlist_name": "Restored",
        })
        created = {
            "id": "new-id",
            "name": "Restored",
            "public": False,
            "collaborative": False,
            "owner": {"id": "owner"},
            "snapshot_id": "snap",
            "external_urls": {"spotify": "https://playlist/new-id"},
        }
        with (
            patch(
                "restore_playlist.find_restoration_playlists", return_value=[]
            ) as find,
            patch("restore_playlist.create_restoration_playlist", return_value=created),
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ) as save_state,
        ):
            result = restore_playlist._ensure_destination(
                object(), state, "owner"
            )
        self.assertEqual(result["destination_playlist_id"], "new-id")
        self.assertEqual(result["destination_playlist_url"], "https://playlist/new-id")
        self.assertEqual(result["destination_owner_id"], "owner")
        self.assertGreaterEqual(save_state.call_count, 2)
        find.assert_not_called()

    def test_uncertain_creation_recovers_exactly_one_run_id_match(self):
        state = restoration_state([])
        state.update({
            "destination_playlist_id": "",
            "destination_visibility": "private",
            "destination_playlist_name": "Restored",
        })
        recovered = {
            "id": "recovered",
            "name": "Restored",
            "public": False,
            "collaborative": False,
            "owner": {"id": "owner"},
            "snapshot_id": "snap",
            "external_urls": {"spotify": "https://playlist/recovered"},
        }
        with (
            patch(
                "restore_playlist.find_restoration_playlists",
                return_value=[recovered],
            ),
            patch(
                "restore_playlist.create_restoration_playlist",
                side_effect=RequestException("uncertain"),
            ),
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
        ):
            result = restore_playlist._ensure_destination(
                object(), state, "owner"
            )
        self.assertEqual(result["destination_playlist_id"], "recovered")

    def test_uncertain_creation_without_match_never_creates_twice(self):
        state = restoration_state([])
        state.update({
            "destination_playlist_id": "",
            "destination_visibility": "private",
            "destination_playlist_name": "Restored",
            "status": "planned",
        })
        with (
            patch(
                "restore_playlist.find_restoration_playlists",
                side_effect=[[], []],
            ),
            patch(
                "restore_playlist.create_restoration_playlist",
                side_effect=RequestException("connection lost"),
            ) as create,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
        ):
            with self.assertRaises(restore_playlist.CreationOutcomeUncertain):
                restore_playlist._ensure_destination(
                    object(), state, "owner"
                )
        create.assert_called_once()
        self.assertEqual(state["status"], "creation_uncertain")

    def test_server_error_creation_is_treated_as_uncertain(self):
        state = restoration_state([])
        state.update({
            "destination_playlist_id": "",
            "destination_visibility": "private",
            "destination_playlist_name": "Restored",
            "status": "planned",
        })
        error = restore_playlist.SpotifyException(500, -1, "server error")
        with (
            patch(
                "restore_playlist.find_restoration_playlists",
                return_value=[],
            ),
            patch(
                "restore_playlist.create_restoration_playlist",
                side_effect=error,
            ),
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
        ):
            with self.assertRaises(restore_playlist.CreationOutcomeUncertain):
                restore_playlist._ensure_destination(
                    object(), state, "owner"
                )
        self.assertEqual(state["status"], "creation_uncertain")

    def test_later_uncertain_resume_requires_separate_retry_consent(self):
        state = restoration_state([])
        state.update({
            "destination_playlist_id": "",
            "destination_visibility": "private",
            "destination_playlist_name": "Restored",
            "status": "creation_uncertain",
        })
        with (
            patch(
                "restore_playlist.find_restoration_playlists",
                return_value=[],
            ),
            patch("restore_playlist.create_restoration_playlist") as create,
        ):
            with self.assertRaises(restore_playlist.CreationOutcomeUncertain):
                restore_playlist._ensure_destination(
                    object(), state, "owner"
                )
        create.assert_not_called()

        created = {
            "id": "new-id",
            "name": "Restored",
            "public": False,
            "collaborative": False,
            "owner": {"id": "owner"},
            "snapshot_id": "snap",
            "external_urls": {"spotify": "https://playlist/new-id"},
        }
        with (
            patch(
                "restore_playlist.find_restoration_playlists",
                side_effect=[[], []],
            ),
            patch(
                "restore_playlist.create_restoration_playlist",
                return_value=created,
            ) as create,
            patch("builtins.input", return_value="2"),
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            redirect_stdout(StringIO()),
        ):
            result = restore_playlist._resolve_uncertain_creation(
                object(), state, "owner"
            )
        create.assert_called_once()
        self.assertEqual(result["destination_playlist_id"], "new-id")

    def test_uncertain_retry_cancel_does_not_create(self):
        state = restoration_state([])
        state.update({
            "destination_playlist_id": "",
            "destination_visibility": "private",
            "destination_playlist_name": "Restored",
            "status": "creation_uncertain",
        })
        with (
            patch(
                "restore_playlist.find_restoration_playlists",
                return_value=[],
            ),
            patch("restore_playlist.create_restoration_playlist") as create,
            patch("builtins.input", return_value="3"),
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            redirect_stdout(StringIO()),
        ):
            result = restore_playlist._resolve_uncertain_creation(
                object(), state, "owner"
            )
        self.assertIsNone(result)
        create.assert_not_called()

    def test_state_and_report_bundle_validation_rejects_corruption(self):
        plan = small_plan()
        path = restoration_manager.report_path_for_run("validation")
        state = restoration_manager.create_initial_state(
            plan, "validation", "Restored", False, path
        )
        report = restoration_manager.build_report(plan, "validation")
        self.assertTrue(
            restoration_manager.validate_restoration_bundle(
                state, report, plan
            )
        )

        state_changes = {
            "format": ("state_format_version", "999"),
            "status": ("status", "mystery"),
            "run": ("run_id", ""),
            "source": ("source_playlist_id", "wrong"),
            "hash": ("plan_hash", "wrong"),
            "sequence": ("planned_uris", list(reversed(plan["uris"]))),
            "name": ("destination_playlist_name", ""),
            "visibility": ("destination_visibility", "friends"),
            "confirmed": (
                "last_confirmed_destination_length",
                plan["ready_count"] + 1,
            ),
            "path": ("report_path", os.path.join(ROOT, "outside.csv")),
            "premature destination": (
                "destination_playlist_id",
                "unexpected",
            ),
        }
        for label, (key, value) in state_changes.items():
            with self.subTest(state=label):
                damaged = json.loads(json.dumps(state))
                damaged[key] = value
                with self.assertRaises(ValueError):
                    restoration_manager.validate_restoration_bundle(
                        damaged, report, plan
                    )

        report_changes = []
        missing_row = json.loads(json.dumps(report[:-1]))
        report_changes.append(("row count", missing_row))
        missing_column = json.loads(json.dumps(report))
        missing_column[0].pop("Artist")
        report_changes.append(("schema", missing_column))
        wrong_run = json.loads(json.dumps(report))
        wrong_run[0]["Run ID"] = "wrong"
        report_changes.append(("run", wrong_run))
        wrong_snapshot = json.loads(json.dumps(report))
        wrong_snapshot[0]["Source Snapshot ID"] = "wrong"
        report_changes.append(("snapshot", wrong_snapshot))
        wrong_identity = json.loads(json.dumps(report))
        wrong_identity[0]["Spotify URI"] = "spotify:track:replacement"
        report_changes.append(("identity", wrong_identity))
        wrong_destination_position = json.loads(json.dumps(report))
        wrong_destination_position[0]["Destination Position"] = "999"
        report_changes.append(
            ("destination position", wrong_destination_position)
        )
        wrong_result = json.loads(json.dumps(report))
        wrong_result[0]["Result"] = "Skipped"
        report_changes.append(("result", wrong_result))
        wrong_exclusion = json.loads(json.dumps(report))
        excluded_index = next(
            index
            for index, row in enumerate(wrong_exclusion)
            if row["Result"] == "Not included"
        )
        wrong_exclusion[excluded_index]["Result"] = "Pending"
        report_changes.append(("excluded result", wrong_exclusion))
        for label, damaged in report_changes:
            with self.subTest(report=label):
                with self.assertRaises(ValueError):
                    restoration_manager.validate_restoration_bundle(
                        state, damaged, plan
                    )

    def test_confirmed_resume_clears_temporary_failure_reason(self):
        plan = small_plan()
        report = restoration_manager.build_report(plan, "run")
        state = restoration_state(plan["uris"])
        restoration_manager.mark_report_failed(
            report, 1, 2, "Temporary rejection."
        )
        self.assertEqual(
            [report[0]["Result"], report[1]["Result"]],
            ["Failed", "Failed"],
        )
        restoration_manager.update_report(report, state, confirmed_length=2)
        self.assertEqual(
            [report[0]["Result"], report[1]["Result"]],
            ["Added", "Added"],
        )
        self.assertEqual([report[0]["Reason"], report[1]["Reason"]], ["", ""])


class SpotifyRestorationApiTests(unittest.TestCase):
    def test_private_and_public_use_separate_minimal_scopes_and_cache(self):
        for public, expected in (
            (False, "playlist-modify-private"),
            (True, "playlist-modify-public"),
        ):
            with self.subTest(public=public):
                spotify = Mock()
                spotify.current_user.return_value = {"id": "owner"}
                with (
                    patch("spotify_api.SpotifyOAuth") as oauth,
                    patch("spotify_api.spotipy.Spotify", return_value=spotify),
                    patch("spotify_api.requests.Session"),
                ):
                    spotify_api.connect_spotify_restoration(public=public)
                kwargs = oauth.call_args.kwargs
                self.assertIn(expected, kwargs["scope"])
                other = (
                    "playlist-modify-public"
                    if not public else "playlist-modify-private"
                )
                self.assertNotIn(other, kwargs["scope"])
                self.assertTrue(kwargs["cache_path"].endswith(".cache-restoration"))

    def test_creation_uses_current_me_endpoint_method_only(self):
        spotify = Mock()
        spotify.current_user_playlist_create.return_value = {"id": "new"}
        result = spotify_api.create_restoration_playlist(
            spotify, "Exact Name", False, "description"
        )
        self.assertEqual(result["id"], "new")
        spotify.current_user_playlist_create.assert_called_once_with(
            "Exact Name",
            public=False,
            collaborative=False,
            description="description",
        )
        spotify.user_playlist_create.assert_not_called()

    def test_visibility_change_uses_narrow_details_operation(self):
        spotify = Mock()
        spotify_api.change_restoration_playlist_visibility(
            spotify, "destination", False
        )
        spotify.playlist_change_details.assert_called_once_with(
            "destination",
            public=False,
            collaborative=False,
        )
        with self.assertRaises(ValueError):
            spotify_api.change_restoration_playlist_visibility(
                spotify, "destination", None
            )

    def test_add_operation_enforces_batch_limit_and_order(self):
        spotify = Mock()
        uris = [f"spotify:track:{index}" for index in range(100)]
        spotify_api.add_restoration_items(
            spotify, "destination", uris, position=200
        )
        spotify.playlist_add_items.assert_called_once_with(
            "destination", uris, position=200
        )
        with self.assertRaises(ValueError):
            spotify_api.add_restoration_items(
                spotify,
                "destination",
                uris + ["spotify:track:extra"],
                position=200,
            )

    def test_destination_read_is_snapshot_stable(self):
        spotify = Mock()
        spotify.playlist.side_effect = [
            spotify_playlist_details(2),
            spotify_playlist_details(2),
        ]
        spotify.playlist_items.return_value = {
            "items": [
                {"item": {"uri": "spotify:track:a"}},
                {"item": {"uri": "spotify:track:b"}},
            ],
            "next": None,
        }
        result = spotify_api.get_destination_playlist(
            spotify, "destination"
        )
        self.assertEqual(
            result["uris"], ["spotify:track:a", "spotify:track:b"]
        )
        self.assertEqual(result["reported_total"], 2)
        self.assertEqual(spotify.playlist.call_count, 2)

    def test_destination_read_preserves_null_visibility_as_unknown(self):
        spotify = Mock()
        spotify.playlist.side_effect = [
            spotify_playlist_details(0, public=None),
            spotify_playlist_details(0, public=None),
        ]
        spotify.playlist_items.return_value = {
            "items": [],
            "next": None,
        }
        result = spotify_api.get_destination_playlist(
            spotify, "destination"
        )
        self.assertIsNone(result["public"])

    def test_destination_change_during_pagination_is_rejected(self):
        spotify = Mock()
        spotify.playlist.side_effect = [
            spotify_playlist_details(1, snapshot="before"),
            spotify_playlist_details(1, snapshot="after"),
        ]
        spotify.playlist_items.return_value = {
            "items": [{"item": {"uri": "spotify:track:a"}}],
            "next": None,
        }
        with self.assertRaisesRegex(ValueError, "changed while"):
            spotify_api.get_destination_playlist(spotify, "destination")

    def test_destination_row_count_must_match_stable_reported_total(self):
        spotify = Mock()
        spotify.playlist.side_effect = [
            spotify_playlist_details(2),
            spotify_playlist_details(2),
        ]
        spotify.playlist_items.return_value = {
            "items": [{"item": {"uri": "spotify:track:a"}}],
            "next": None,
        }
        with self.assertRaisesRegex(ValueError, "reported total"):
            spotify_api.get_destination_playlist(spotify, "destination")


class VisibilityEnforcementTests(unittest.TestCase):
    def test_created_private_then_get_public_is_corrected_before_items(self):
        plan = small_plan()
        state = restoration_manager.create_initial_state(
            plan,
            "run-1",
            "Restored",
            False,
            restoration_manager.report_path_for_run("run-1"),
        )
        report = restoration_manager.build_report(plan, "run-1")
        created = {
            "id": "destination",
            "name": "Restored",
            "public": False,
            "collaborative": False,
            "description": (
                "Restored by Music Museum Toolkit. Restoration run: run-1"
            ),
            "owner": {"id": "owner"},
            "snapshot_id": "creation-response",
            "external_urls": {
                "spotify": "https://open.spotify.com/playlist/destination"
            },
        }
        spotify = object()
        with (
            patch(
                "restore_playlist.create_restoration_playlist",
                return_value=created,
            ) as create,
            patch(
                "restore_playlist.change_restoration_playlist_visibility"
            ) as change_visibility,
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([], public=True, snapshot="reported-public"),
                    destination([], public=False, snapshot="verified-private"),
                    destination([], public=False, snapshot="initial-prefix"),
                    destination(
                        plan["uris"],
                        public=False,
                        snapshot="final",
                    ),
                ],
            ),
            patch(
                "restore_playlist.add_restoration_items",
                return_value={"snapshot_id": "added"},
            ) as add,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            patch("restore_playlist.save_report"),
        ):
            state = restore_playlist._ensure_destination(
                spotify, state, "owner"
            )
            restoration_manager.update_report(report, state)
            result = restore_playlist._restore_verified_destination(
                spotify,
                state,
                report,
                plan,
                "owner",
            )
        create.assert_called_once()
        change_visibility.assert_called_once_with(
            spotify, "destination", False
        )
        add.assert_called_once()
        self.assertEqual(result["status"], "complete")

    def test_existing_public_destination_is_corrected_without_second_create(self):
        plan, state, report = visibility_bundle(public=False)
        spotify = object()
        with (
            patch("restore_playlist.create_restoration_playlist") as create,
            patch(
                "restore_playlist.change_restoration_playlist_visibility"
            ) as change_visibility,
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([], public=True, snapshot="public"),
                    destination([], public=False, snapshot="private"),
                    destination([], public=False, snapshot="initial"),
                    destination(
                        plan["uris"],
                        public=False,
                        snapshot="final",
                    ),
                ],
            ),
            patch(
                "restore_playlist.add_restoration_items",
                return_value={"snapshot_id": "added"},
            ) as add,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            patch("restore_playlist.save_report"),
        ):
            state = restore_playlist._ensure_destination(
                spotify, state, "owner"
            )
            result = restore_playlist._restore_verified_destination(
                spotify,
                state,
                report,
                plan,
                "owner",
            )
        create.assert_not_called()
        change_visibility.assert_called_once_with(
            spotify, "destination", False
        )
        add.assert_called_once()
        self.assertEqual(result["status"], "complete")

    def test_existing_requested_visibility_needs_no_mutation(self):
        plan, state, report = visibility_bundle(public=False)
        spotify = object()
        with (
            patch("restore_playlist.create_restoration_playlist") as create,
            patch(
                "restore_playlist.change_restoration_playlist_visibility"
            ) as change_visibility,
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([], public=False, snapshot="already-private"),
                    destination([], public=False, snapshot="initial"),
                    destination(
                        plan["uris"],
                        public=False,
                        snapshot="final",
                    ),
                ],
            ),
            patch(
                "restore_playlist.add_restoration_items",
                return_value={"snapshot_id": "added"},
            ),
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            patch("restore_playlist.save_report"),
        ):
            state = restore_playlist._ensure_destination(
                spotify, state, "owner"
            )
            result = restore_playlist._restore_verified_destination(
                spotify,
                state,
                report,
                plan,
                "owner",
            )
        create.assert_not_called()
        change_visibility.assert_not_called()
        self.assertEqual(result["status"], "complete")

    def test_public_restoration_explicitly_enforces_public(self):
        plan, state, report = visibility_bundle(public=True)
        spotify = object()
        with (
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([], public=False, snapshot="private"),
                    destination([], public=True, snapshot="public"),
                ],
            ),
            patch(
                "restore_playlist.change_restoration_playlist_visibility"
            ) as change_visibility,
        ):
            verified = restore_playlist._enforce_destination_visibility(
                spotify,
                state,
                report,
                plan,
                "owner",
            )
        change_visibility.assert_called_once_with(
            spotify, "destination", True
        )
        self.assertIs(verified["public"], True)

    def test_identity_or_run_marker_mismatch_prevents_visibility_mutation(self):
        plan, state, report = visibility_bundle(public=False)
        cases = {
            "playlist ID": {"playlist_id": "other"},
            "owner": {"owner": "other"},
            "name": {"name": "Other"},
            "collaboration": {"collaborative": True},
            "run marker": {
                "description": (
                    "Restored by Music Museum Toolkit. "
                    "Restoration run: different"
                )
            },
        }
        for label, changes in cases.items():
            with self.subTest(label=label):
                spotify = object()
                with (
                    patch(
                        "restore_playlist.get_destination_playlist",
                        return_value=destination(
                            [],
                            public=True,
                            **changes,
                        ),
                    ),
                    patch(
                        "restore_playlist."
                        "change_restoration_playlist_visibility"
                    ) as change_visibility,
                    patch(
                        "restore_playlist.add_restoration_items"
                    ) as add,
                ):
                    with self.assertRaises(ValueError):
                        restore_playlist._restore_verified_destination(
                            spotify,
                            state,
                            report,
                            plan,
                            "owner",
                        )
                change_visibility.assert_not_called()
                add.assert_not_called()

    def test_visibility_update_failure_adds_nothing_and_keeps_state(self):
        plan, state, report = visibility_bundle(public=False)
        original_state = dict(state)
        with (
            patch(
                "restore_playlist.get_destination_playlist",
                return_value=destination([], public=True),
            ),
            patch(
                "restore_playlist.change_restoration_playlist_visibility",
                side_effect=RequestException("connection lost"),
            ),
            patch("restore_playlist.add_restoration_items") as add,
        ):
            with self.assertRaises(RequestException):
                restore_playlist._restore_verified_destination(
                    object(),
                    state,
                    report,
                    plan,
                    "owner",
                )
        add.assert_not_called()
        self.assertEqual(state, original_state)

    def test_incorrect_or_null_visibility_stops_after_bounded_reads(self):
        plan, state, report = visibility_bundle(public=False)
        for label, stale_value in (("public", True), ("null", None)):
            with self.subTest(label=label):
                with (
                    patch(
                        "restore_playlist.get_destination_playlist",
                        side_effect=[
                            destination([], public=True),
                            destination([], public=stale_value),
                            destination([], public=stale_value),
                            destination([], public=stale_value),
                        ],
                    ) as read_destination,
                    patch(
                        "restore_playlist."
                        "change_restoration_playlist_visibility"
                    ) as change_visibility,
                    patch("restore_playlist.time.sleep") as sleep,
                    patch(
                        "restore_playlist.add_restoration_items"
                    ) as add,
                ):
                    with self.assertRaisesRegex(
                        ValueError, "could not be verified as private"
                    ):
                        restore_playlist._restore_verified_destination(
                            object(),
                            state,
                            report,
                            plan,
                            "owner",
                        )
                change_visibility.assert_called_once()
                self.assertEqual(read_destination.call_count, 4)
                self.assertEqual(sleep.call_count, 2)
                add.assert_not_called()
                self.assertEqual(
                    state["last_confirmed_destination_length"], 0
                )


class ReconciliationTests(unittest.TestCase):
    def test_duplicate_aware_prefix_and_mismatch_refusal(self):
        plan = ["a", "a", "b"]
        self.assertEqual(
            restoration_manager.exact_prefix_length(["a", "a"], plan), 2
        )
        for remote in (["a", "b"], ["a", "a", "b", "extra"], ["a", ""]):
            with self.subTest(remote=remote):
                with self.assertRaises(ValueError):
                    restoration_manager.exact_prefix_length(remote, plan)

    def test_resume_uses_remote_prefix_and_exact_order(self):
        planned = ["a", "a", "b"]
        state = restoration_state(planned)
        report = []
        spotify = object()
        with (
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination(["a"]),
                    destination(planned, snapshot="final"),
                ],
            ) as read_destination,
            patch(
                "restore_playlist.add_restoration_items",
                return_value={"snapshot_id": "after-add"},
            ) as add,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            patch("restore_playlist.save_report"),
        ):
            result = restore_playlist._restore_batches(
                spotify, state, report, "owner"
            )
        add.assert_called_once_with(
            spotify, "destination", ["a", "b"], position=1
        )
        self.assertEqual(read_destination.call_count, 2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["last_confirmed_destination_length"], 3)

    def test_1274_successful_items_use_13_positioned_adds_and_two_full_reads(self):
        collection, manifest, sync_state = preservation_fixture()
        plan = restoration_manager.build_restoration_plan(
            collection, manifest, sync_state
        )
        state = restoration_state(plan["uris"])
        saved_states = []

        def capture_state(value):
            saved_states.append(dict(value))
            return value

        with (
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([], snapshot="initial"),
                    destination(plan["uris"], snapshot="final"),
                ],
            ) as read_destination,
            patch(
                "restore_playlist.add_restoration_items",
                side_effect=[
                    {"snapshot_id": f"batch-{index}"}
                    for index in range(1, 14)
                ],
            ) as add,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=capture_state,
            ),
            patch("restore_playlist.save_report"),
        ):
            result = restore_playlist._restore_batches(
                object(), state, [], "owner"
            )

        self.assertEqual(add.call_count, 13)
        self.assertEqual(read_destination.call_count, 2)
        positions = [
            call.kwargs["position"] for call in add.call_args_list
        ]
        self.assertEqual(positions, list(range(0, 1300, 100)))
        self.assertTrue(
            all(len(call.args[2]) <= 100 for call in add.call_args_list)
        )
        checkpoint_lengths = [
            saved["last_confirmed_destination_length"]
            for saved in saved_states
            if saved["status"] == "in_progress"
        ]
        self.assertEqual(
            checkpoint_lengths,
            [0] + list(range(100, 1201, 100)) + [1274],
        )
        self.assertEqual(result["status"], "complete")

    def test_missing_success_snapshot_forces_full_reconciliation(self):
        planned = ["a", "b"]
        state = restoration_state(planned)
        with (
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([], snapshot="initial"),
                    destination(planned, snapshot="reconciled"),
                    destination(planned, snapshot="final"),
                ],
            ) as read_destination,
            patch(
                "restore_playlist.add_restoration_items",
                return_value={},
            ) as add,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            patch("restore_playlist.save_report"),
        ):
            result = restore_playlist._restore_batches(
                object(), state, [], "owner"
            )
        add.assert_called_once_with(
            unittest.mock.ANY,
            "destination",
            planned,
            position=0,
        )
        self.assertEqual(read_destination.call_count, 3)
        self.assertEqual(result["status"], "complete")

    def test_ambiguous_success_is_reconciled_without_duplicate_retry(self):
        planned = ["a", "b"]
        state = restoration_state(planned)
        with (
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([]),
                    destination(planned, snapshot="ambiguous-success"),
                    destination(planned, snapshot="final"),
                ],
            ),
            patch(
                "restore_playlist.add_restoration_items",
                side_effect=RequestException("connection lost"),
            ) as add,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            patch("restore_playlist.save_report"),
        ):
            result = restore_playlist._restore_batches(
                object(), state, [], "owner"
            )
        add.assert_called_once()
        self.assertEqual(result["status"], "complete")

    def test_server_error_add_success_is_reconciled_without_duplicate(self):
        planned = ["a", "b"]
        state = restoration_state(planned)
        error = restore_playlist.SpotifyException(500, -1, "server error")
        with (
            patch(
                "restore_playlist.get_destination_playlist",
                side_effect=[
                    destination([]),
                    destination(planned, snapshot="server-success"),
                    destination(planned, snapshot="final"),
                ],
            ),
            patch(
                "restore_playlist.add_restoration_items",
                side_effect=error,
            ) as add,
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ),
            patch("restore_playlist.save_report"),
        ):
            result = restore_playlist._restore_batches(
                object(), state, [], "owner"
            )
        add.assert_called_once()
        self.assertEqual(result["status"], "complete")

    def test_rate_limit_checkpoints_without_marking_progress(self):
        state = restoration_state(["a"])
        with (
            patch(
                "restore_playlist.get_destination_playlist",
                return_value=destination([]),
            ),
            patch(
                "restore_playlist.add_restoration_items",
                side_effect=spotify_api.SpotifyRateLimit(120),
            ),
            patch(
                "restore_playlist.save_restoration_state",
                side_effect=lambda value: value,
            ) as save_state,
            patch("restore_playlist.save_report") as save_report,
        ):
            with self.assertRaises(spotify_api.SpotifyRateLimit):
                restore_playlist._restore_batches(object(), state, [], "owner")
        self.assertGreaterEqual(save_state.call_count, 2)
        save_report.assert_called()
        self.assertEqual(state["last_confirmed_destination_length"], 0)

    def test_final_verification_requires_exact_sequence(self):
        self.assertTrue(restoration_manager.verify_complete(["a", "a"], ["a", "a"]))
        for remote in (["a"], ["a", "b"], ["a", "a", "b"]):
            with self.assertRaises(ValueError):
                restoration_manager.verify_complete(remote, ["a", "a"])


class RestorationWorkflowTests(unittest.TestCase):
    def test_cancellation_before_authentication_makes_no_spotify_change(self):
        plan = small_plan()
        with (
            patch("restore_playlist.load_existing_collection"),
            patch("restore_playlist.load_manifest"),
            patch("restore_playlist.load_sync_state"),
            patch("restore_playlist.build_restoration_plan", return_value=plan),
            patch("restore_playlist.load_restoration_state", return_value={}),
            patch("builtins.input", side_effect=["n", "Name", "1", "n"]),
            patch("restore_playlist.connect_spotify_restoration") as connect,
            patch("restore_playlist.create_restoration_playlist") as create,
            redirect_stdout(StringIO()),
        ):
            restore_playlist.main()
        connect.assert_not_called()
        create.assert_not_called()

    def test_invalid_local_data_prevents_authentication(self):
        with (
            patch("restore_playlist.load_existing_collection"),
            patch("restore_playlist.load_manifest"),
            patch("restore_playlist.load_sync_state"),
            patch(
                "restore_playlist.build_restoration_plan",
                side_effect=ValueError("bad preservation data"),
            ),
            patch("restore_playlist.connect_spotify_restoration") as connect,
            redirect_stdout(StringIO()),
        ):
            restore_playlist.main()
        connect.assert_not_called()

    def test_corrupt_in_progress_report_prevents_authentication(self):
        plan = small_plan()
        state = restoration_manager.create_initial_state(
            plan,
            "corrupt-run",
            "Partial",
            False,
            restoration_manager.report_path_for_run("corrupt-run"),
        )
        report = restoration_manager.build_report(plan, "corrupt-run")
        report[0]["Run ID"] = "different-run"
        with (
            patch("restore_playlist.load_existing_collection"),
            patch("restore_playlist.load_manifest"),
            patch("restore_playlist.load_sync_state"),
            patch("restore_playlist.build_restoration_plan", return_value=plan),
            patch("restore_playlist.load_restoration_state", return_value=state),
            patch("restore_playlist.load_report", return_value=report),
            patch("restore_playlist.connect_spotify_restoration") as connect,
            redirect_stdout(StringIO()),
        ):
            restore_playlist.main()
        connect.assert_not_called()

    def test_corrupt_in_progress_state_prevents_authentication(self):
        plan = small_plan()
        state = restoration_manager.create_initial_state(
            plan,
            "corrupt-state",
            "Partial",
            False,
            restoration_manager.report_path_for_run("corrupt-state"),
        )
        state["status"] = "unknown"
        with (
            patch("restore_playlist.load_existing_collection"),
            patch("restore_playlist.load_manifest"),
            patch("restore_playlist.load_sync_state"),
            patch("restore_playlist.build_restoration_plan", return_value=plan),
            patch("restore_playlist.load_restoration_state", return_value=state),
            patch("restore_playlist.connect_spotify_restoration") as connect,
            redirect_stdout(StringIO()),
        ):
            restore_playlist.main()
        connect.assert_not_called()

    def test_incomplete_restoration_is_detected_before_new_creation(self):
        plan = small_plan()
        state = restoration_manager.create_initial_state(
            plan,
            "run",
            "Partial",
            False,
            restoration_manager.report_path_for_run("run"),
        )
        state.update({
            "destination_playlist_id": "destination",
            "destination_playlist_url": "https://playlist/destination",
            "destination_owner_id": "owner",
            "last_confirmed_destination_length": 2,
            "status": "in_progress",
        })
        output = StringIO()
        with (
            patch("restore_playlist.load_existing_collection"),
            patch("restore_playlist.load_manifest"),
            patch("restore_playlist.load_sync_state"),
            patch("restore_playlist.build_restoration_plan", return_value=plan),
            patch("restore_playlist.load_restoration_state", return_value=state),
            patch(
                "restore_playlist.load_report",
                return_value=restoration_manager.build_report(plan, "run"),
            ),
            patch("builtins.input", return_value="2"),
            patch("restore_playlist.connect_spotify_restoration") as connect,
            redirect_stdout(output),
        ):
            restore_playlist.main()
        self.assertIn("Incomplete restoration found", output.getvalue())
        connect.assert_not_called()

    def test_restoration_never_calls_preservation_save_functions(self):
        plan = small_plan()
        with (
            patch("restore_playlist.load_existing_collection"),
            patch("restore_playlist.load_manifest"),
            patch("restore_playlist.load_sync_state"),
            patch("restore_playlist.build_restoration_plan", return_value=plan),
            patch("restore_playlist.load_restoration_state", return_value={}),
            patch("builtins.input", side_effect=["n", "",]),
            patch("collection_manager.save_collection") as collection_save,
            patch("manifest_manager.save_manifest") as manifest_save,
            redirect_stdout(StringIO()),
        ):
            restore_playlist.main()
        collection_save.assert_not_called()
        manifest_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
