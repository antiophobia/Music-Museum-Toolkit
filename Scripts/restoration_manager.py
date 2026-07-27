"""Validation, state, reporting, and reconciliation for playlist restoration."""

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd

from collection_manager import assert_valid_collection
from manifest_manager import assert_valid_manifest


STATE_FORMAT_VERSION = "1"
MAX_BATCH_SIZE = 100
ALLOWED_STATE_STATUSES = {
    "planned",
    "creating",
    "creation_uncertain",
    "creation_blocked",
    "created",
    "in_progress",
    "blocked",
    "complete",
}
ALLOWED_REPORT_RESULTS = {"Added", "Not included", "Pending", "Failed"}
RESTORABLE_CLASSIFICATIONS = {"valid track", "duplicate occurrence"}
NONRESTORABLE_CLASSIFICATIONS = {
    "local file",
    "unavailable entry",
    "unsupported entry",
    "malformed entry",
}
REPORT_COLUMNS = [
    "Run ID",
    "Source Snapshot ID",
    "Destination Playlist ID",
    "Destination Playlist URL",
    "Original Playlist Position",
    "Destination Position",
    "Museum ID",
    "Source Track ID",
    "Spotify URI",
    "Title",
    "Artist",
    "Classification",
    "Result",
    "Reason",
    "Last Updated At",
]


def _output_path(*parts):
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "Output", *parts)
    )


RESTORATION_STATE_PATH = _output_path("restoration_state.json")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def load_sync_state(path=None):
    path = path or _output_path("playlist_sync.json")
    try:
        with open(path, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load completed playlist state: {error}") from error
    if not isinstance(state, dict):
        raise ValueError("Completed playlist state must be an object.")
    return state


def load_restoration_state(path=None):
    path = path or RESTORATION_STATE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Restoration state cannot be read safely: {error}") from error
    if not isinstance(state, dict):
        raise ValueError("Restoration state must be an object.")
    return state


def _atomic_json(data, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as output:
        json.dump(data, output, indent=2)
    os.replace(temporary_path, path)


def save_restoration_state(state, path=None):
    state = dict(state)
    state["updated_at"] = utc_now()
    _atomic_json(state, path or RESTORATION_STATE_PATH)
    return state


def plan_hash(uris):
    payload = json.dumps(list(uris), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_restoration_plan(collection, manifest, sync_state):
    """Validate latest preserved data and build an exact ordered URI plan."""
    assert_valid_collection(collection)
    complete_snapshot = _text(sync_state.get("complete_snapshot"))
    playlist_id = _text(sync_state.get("playlist_id"))
    playlist_name = _text(sync_state.get("playlist_name"))
    report = sync_state.get("last_report")
    if not complete_snapshot or not playlist_id or not isinstance(report, dict):
        raise ValueError("playlist_sync.json has no valid completed snapshot.")
    if manifest.empty:
        raise ValueError("The completed playlist manifest is empty.")
    manifest_snapshot = _text(manifest.iloc[0].get("Snapshot ID"))
    if manifest_snapshot != complete_snapshot:
        raise ValueError(
            "The playlist manifest snapshot does not match the completed snapshot."
        )
    assert_valid_manifest(
        manifest,
        collection,
        playlist_id,
        playlist_name,
        complete_snapshot,
        report,
    )

    museum_by_source = {
        _text(row.get("Source Track ID")): _text(row.get("Museum ID"))
        for _, row in collection.iterrows()
    }
    planned = []
    excluded = []
    for _, row in manifest.iterrows():
        item = {column: _text(row.get(column)) for column in manifest.columns}
        classification = item["Classification"]
        if classification in RESTORABLE_CLASSIFICATIONS:
            source_id = item["Source Track ID"]
            expected_uri = f"spotify:track:{source_id}" if source_id else ""
            if item["Restorable"] != "True":
                raise ValueError(
                    f"Position {item['Playlist Position']} is not marked restorable."
                )
            if not source_id or item["Spotify URI"] != expected_uri:
                raise ValueError(
                    f"Position {item['Playlist Position']} has invalid stored "
                    "Spotify track identity."
                )
            expected_museum_id = museum_by_source.get(source_id, "")
            if not expected_museum_id or item["Museum ID"] != expected_museum_id:
                raise ValueError(
                    f"Position {item['Playlist Position']} has invalid Museum ID "
                    "mapping."
                )
            item["Destination Position"] = str(len(planned) + 1)
            planned.append(item)
        elif classification in NONRESTORABLE_CLASSIFICATIONS:
            item["Destination Position"] = ""
            excluded.append(item)
        else:
            raise ValueError(
                f"Position {item['Playlist Position']} has unknown classification."
            )

    uris = [item["Spotify URI"] for item in planned]
    counts = manifest["Classification"].value_counts().to_dict()
    return {
        "source_playlist_id": playlist_id,
        "source_playlist_name": playlist_name,
        "source_snapshot_id": complete_snapshot,
        "source_captured_at": _text(manifest.iloc[0].get("Captured At")),
        "manifest_occurrences": len(manifest),
        "planned": planned,
        "excluded": excluded,
        "uris": uris,
        "plan_hash": plan_hash(uris),
        "ready_count": len(planned),
        "excluded_count": len(excluded),
        "batch_count": (len(planned) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE,
        "classification_counts": {
            classification: int(counts.get(classification, 0))
            for classification in NONRESTORABLE_CLASSIFICATIONS
        },
    }


def batches(uris, size=MAX_BATCH_SIZE):
    if size < 1 or size > MAX_BATCH_SIZE:
        raise ValueError("Restoration batch size must be between 1 and 100.")
    for index in range(0, len(uris), size):
        yield list(uris[index:index + size])


def new_run_id():
    return uuid4().hex


def restoration_description(run_id):
    return f"Restored by Music Museum Toolkit. Restoration run: {run_id}"


def create_initial_state(plan, run_id, name, public, report_path):
    now = utc_now()
    return {
        "state_format_version": STATE_FORMAT_VERSION,
        "run_id": run_id,
        "source_playlist_id": plan["source_playlist_id"],
        "source_manifest_snapshot_id": plan["source_snapshot_id"],
        "source_manifest_captured_at": plan["source_captured_at"],
        "plan_hash": plan["plan_hash"],
        "total_planned_item_count": plan["ready_count"],
        "planned_uris": list(plan["uris"]),
        "destination_playlist_id": "",
        "destination_playlist_url": "",
        "destination_playlist_name": name,
        "destination_visibility": "public" if public else "private",
        "destination_owner_id": "",
        "last_confirmed_destination_length": 0,
        "last_returned_destination_snapshot_id": "",
        "report_path": report_path,
        "status": "planned",
        "created_at": now,
        "updated_at": now,
    }


def _whole_number(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number.")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a whole number.") from error
    if str(value).strip() not in {str(number), f"{number}.0"}:
        raise ValueError(f"{label} must be a whole number.")
    return number


def _validate_report_path(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Restoration report path is missing.")
    reports_root = os.path.normcase(
        os.path.realpath(_output_path("Restoration Reports"))
    )
    report_path = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    try:
        inside_reports = (
            os.path.commonpath([reports_root, report_path]) == reports_root
        )
    except ValueError:
        inside_reports = False
    if not inside_reports or not report_path.lower().endswith(".csv"):
        raise ValueError(
            "Restoration report path must be a CSV inside "
            "Output/Restoration Reports."
        )
    return report_path


def validate_state_for_plan(state, plan):
    if not state:
        return False
    if state.get("status") == "complete":
        return False
    required = (
        "state_format_version",
        "run_id",
        "source_playlist_id",
        "source_manifest_snapshot_id",
        "source_manifest_captured_at",
        "plan_hash",
        "total_planned_item_count",
        "planned_uris",
        "destination_playlist_name",
        "destination_visibility",
        "last_confirmed_destination_length",
        "report_path",
        "status",
    )
    if any(key not in state for key in required):
        raise ValueError("Restoration state is incomplete and requires user review.")
    if state["status"] not in ALLOWED_STATE_STATUSES:
        raise ValueError("Restoration state has an unsupported status.")
    if not _text(state["run_id"]):
        raise ValueError("Restoration state has no usable run ID.")
    if (
        not _text(state["source_playlist_id"])
        or not _text(state["source_manifest_snapshot_id"])
        or not _text(state["source_manifest_captured_at"])
        or not _text(state["plan_hash"])
    ):
        raise ValueError("Restoration state source identity is incomplete.")
    if not _text(state["destination_playlist_name"]):
        raise ValueError("Restoration destination name is missing.")
    if state["destination_visibility"] not in {"private", "public"}:
        raise ValueError("Restoration destination visibility is invalid.")
    confirmed_length = _whole_number(
        state["last_confirmed_destination_length"],
        "Confirmed destination length",
    )
    if confirmed_length < 0 or confirmed_length > plan["ready_count"]:
        raise ValueError("Confirmed destination length is outside plan bounds.")
    _validate_report_path(state["report_path"])
    total_planned = _whole_number(
        state["total_planned_item_count"], "Total planned item count"
    )
    if not isinstance(state["planned_uris"], list):
        raise ValueError("Restoration state planned URI sequence is invalid.")
    if (
        state["state_format_version"] != STATE_FORMAT_VERSION
        or state["source_playlist_id"] != plan["source_playlist_id"]
        or state["source_manifest_snapshot_id"] != plan["source_snapshot_id"]
        or state["source_manifest_captured_at"] != plan["source_captured_at"]
        or state["plan_hash"] != plan["plan_hash"]
        or total_planned != plan["ready_count"]
        or state["planned_uris"] != plan["uris"]
    ):
        raise ValueError(
            "The in-progress restoration does not match the latest completed manifest."
        )
    destination_id = _text(state.get("destination_playlist_id"))
    if state["status"] in {"created", "in_progress", "blocked"}:
        if (
            not destination_id
            or not _text(state.get("destination_playlist_url"))
            or not _text(state.get("destination_owner_id"))
        ):
            raise ValueError(
                "Restoration state status requires complete destination identity."
            )
    elif destination_id:
        raise ValueError(
            "Restoration state contains a destination before creation was confirmed."
        )
    return state.get("status") != "complete"


def validate_report_for_plan(report_rows, state, plan):
    """Reject a corrupt occurrence report before Spotify is contacted."""
    if not isinstance(report_rows, list) or len(report_rows) != plan[
        "manifest_occurrences"
    ]:
        raise ValueError(
            "Restoration report must contain one row per manifest occurrence."
        )

    expected_items = {
        int(item["Playlist Position"]): item
        for item in plan["planned"] + plan["excluded"]
    }
    seen_positions = set()
    confirmed_length = int(state["last_confirmed_destination_length"])
    for row in report_rows:
        if not isinstance(row, dict) or set(row) != set(REPORT_COLUMNS):
            raise ValueError("Restoration report schema is invalid.")
        if row["Run ID"] != state["run_id"]:
            raise ValueError("Restoration report run ID does not match state.")
        if row["Source Snapshot ID"] != plan["source_snapshot_id"]:
            raise ValueError(
                "Restoration report source snapshot does not match the plan."
            )
        if row["Destination Playlist ID"] not in {
            "",
            _text(state.get("destination_playlist_id")),
        }:
            raise ValueError(
                "Restoration report destination playlist ID is invalid."
            )
        if row["Destination Playlist URL"] not in {
            "",
            _text(state.get("destination_playlist_url")),
        }:
            raise ValueError(
                "Restoration report destination playlist URL is invalid."
            )
        position = _whole_number(
            row["Original Playlist Position"], "Original playlist position"
        )
        if position in seen_positions or position not in expected_items:
            raise ValueError(
                "Restoration report occurrence positions are invalid."
            )
        seen_positions.add(position)
        expected = expected_items[position]
        for report_key, manifest_key in (
            ("Destination Position", "Destination Position"),
            ("Museum ID", "Museum ID"),
            ("Source Track ID", "Source Track ID"),
            ("Spotify URI", "Spotify URI"),
            ("Title", "Title"),
            ("Artist", "Artist"),
            ("Classification", "Classification"),
        ):
            if row[report_key] != expected[manifest_key]:
                raise ValueError(
                    f"Restoration report occurrence {position} does not match "
                    "the restoration plan."
                )

        result = row["Result"]
        if result not in ALLOWED_REPORT_RESULTS:
            raise ValueError("Restoration report contains an unsupported result.")
        if expected["Classification"] in NONRESTORABLE_CLASSIFICATIONS:
            if result != "Not included" or row["Reason"] != expected["Reason"]:
                raise ValueError(
                    "Nonrestorable report rows must retain their manifest reason."
                )
        else:
            destination_position = int(expected["Destination Position"])
            if result == "Not included":
                raise ValueError(
                    "A planned restoration occurrence cannot be Not included."
                )
            if result == "Added" and destination_position > confirmed_length:
                raise ValueError(
                    "Restoration report marks an unconfirmed occurrence as Added."
                )
            if result in {"Pending", "Added"} and row["Reason"]:
                raise ValueError(
                    f"{result} restoration rows cannot retain a failure reason."
                )
            if result == "Failed" and not row["Reason"]:
                raise ValueError("Failed restoration rows require a reason.")

    if seen_positions != set(expected_items):
        raise ValueError(
            "Restoration report does not cover the exact manifest occurrences."
        )
    return True


def validate_restoration_bundle(state, report_rows, plan):
    validate_state_for_plan(state, plan)
    validate_report_for_plan(report_rows, state, plan)
    return True


def report_path_for_run(run_id, timestamp=None):
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return _output_path("Restoration Reports", f"{stamp}-{run_id}.csv")


def build_report(plan, run_id):
    now = utc_now()
    rows = []
    for item in plan["planned"] + plan["excluded"]:
        included = item["Classification"] in RESTORABLE_CLASSIFICATIONS
        rows.append({
            "Run ID": run_id,
            "Source Snapshot ID": plan["source_snapshot_id"],
            "Destination Playlist ID": "",
            "Destination Playlist URL": "",
            "Original Playlist Position": item["Playlist Position"],
            "Destination Position": item["Destination Position"],
            "Museum ID": item["Museum ID"],
            "Source Track ID": item["Source Track ID"],
            "Spotify URI": item["Spotify URI"],
            "Title": item["Title"],
            "Artist": item["Artist"],
            "Classification": item["Classification"],
            "Result": "Pending" if included else "Not included",
            "Reason": "" if included else item["Reason"],
            "Last Updated At": now,
        })
    return sorted(rows, key=lambda row: int(row["Original Playlist Position"]))


def update_report(report_rows, state, confirmed_length=None):
    now = utc_now()
    confirmed_length = (
        int(state.get("last_confirmed_destination_length", 0))
        if confirmed_length is None
        else int(confirmed_length)
    )
    for row in report_rows:
        row["Destination Playlist ID"] = state.get("destination_playlist_id", "")
        row["Destination Playlist URL"] = state.get("destination_playlist_url", "")
        destination = row.get("Destination Position", "")
        if destination and int(destination) <= confirmed_length:
            row["Result"] = "Added"
            row["Reason"] = ""
        row["Last Updated At"] = now
    return report_rows


def mark_report_failed(report_rows, start_position, item_count, reason):
    """Mark only the currently blocked attempted destination occurrences."""
    start_position = int(start_position)
    end_position = start_position + int(item_count) - 1
    now = utc_now()
    for row in report_rows:
        destination = row.get("Destination Position", "")
        if destination and start_position <= int(destination) <= end_position:
            row["Result"] = "Failed"
            row["Reason"] = reason
            row["Last Updated At"] = now
    return report_rows


def save_report(report_rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".tmp"
    with open(temporary_path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(report_rows)
    os.replace(temporary_path, path)
    return path


def load_report(path):
    try:
        with open(path, "r", newline="", encoding="utf-8") as source:
            return list(csv.DictReader(source))
    except OSError as error:
        raise ValueError(f"Restoration report cannot be read safely: {error}") from error


def exact_prefix_length(remote_uris, planned_uris):
    if len(remote_uris) > len(planned_uris):
        raise ValueError("Destination playlist contains extra items.")
    for index, uri in enumerate(remote_uris):
        if not uri:
            raise ValueError(
                f"Destination item {index + 1} is unavailable and cannot be compared."
            )
        if uri != planned_uris[index]:
            raise ValueError(
                f"Destination differs from the restoration plan at item {index + 1}."
            )
    return len(remote_uris)


def verify_complete(remote_uris, planned_uris):
    if len(remote_uris) != len(planned_uris):
        raise ValueError(
            f"Destination has {len(remote_uris)} items; "
            f"{len(planned_uris)} were planned."
        )
    exact_prefix_length(remote_uris, planned_uris)
    return True
