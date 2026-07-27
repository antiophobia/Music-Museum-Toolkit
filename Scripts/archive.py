"""
Music Museum Toolkit
Version 0.3.1 - Validation and hardening
"""

import json
import os
from datetime import datetime, timezone

import pandas as pd
from tqdm import tqdm

from collection_manager import (
    assert_valid_collection,
    build_collection,
    load_checkpoint,
    load_existing_collection,
    remove_checkpoint,
    save_checkpoint,
    save_collection,
)
from manifest_manager import (
    MANIFEST_COLUMNS,
    assert_valid_manifest,
    load_manifest,
    load_manifest_checkpoint,
    map_museum_ids,
    remove_manifest_checkpoint,
    save_manifest,
    save_manifest_checkpoint,
    validate_manifest,
    validate_manifest_checkpoint,
)
from spotify_api import (
    CLASSIFICATION_KEYS,
    SpotifyRateLimit,
    connect_spotify,
    get_playlist_page_occurrences,
    get_playlist_summary,
)


PLAYLIST_ID = "40Pcfa4QeBQsRd0PkGgllM"
PAGE_SIZE = 50
STATE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "Output", "playlist_sync.json")
)


def _text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _artifacts_from_collection(df):
    artifacts = []
    for _, row in df.iterrows():
        track_id = _text(row.get("Source Track ID", ""))
        if not track_id:
            continue
        artifacts.append({
            "Spotify ID": track_id,
            "Title": _text(row.get("Title", "")),
            "Artist": _text(row.get("Artist", "")),
            "Album": _text(row.get("Album", "")),
            "Release Date": _text(row.get("Release Date", "")),
            "Duration (ms)": _text(row.get("Duration (ms)", "")),
            "Popularity": _text(row.get("Popularity", "")),
            "Spotify URL": _text(row.get("Spotify URL", "")),
            "Notes": _text(row.get("Notes", "")),
        })
    return artifacts


def _merge_artifacts(artifacts, additions):
    """Merge metadata safely and report new, updated, and unchanged tracks."""
    changes = {"new_artifacts": 0, "metadata_updates": 0, "unchanged": 0}
    positions = {
        artifact["Spotify ID"]: index
        for index, artifact in enumerate(artifacts)
        if artifact.get("Spotify ID")
    }
    for addition in additions:
        track_id = addition.get("Spotify ID")
        if not track_id:
            continue
        if track_id in positions:
            old = artifacts[positions[track_id]]
            addition["Notes"] = old.get("Notes", "")
            merged = old.copy()
            # Missing optional metadata, including Popularity, is not a change
            # and must not erase a previously preserved value.
            for key, value in addition.items():
                if key == "Notes" or value in (None, ""):
                    continue
                merged[key] = value
            comparable_keys = set(old) | set(merged)
            changed = any(
                _text(old.get(key, "")) != _text(merged.get(key, ""))
                for key in comparable_keys
                if key != "Notes"
            )
            artifacts[positions[track_id]] = merged
            changes["metadata_updates" if changed else "unchanged"] += 1
        else:
            positions[track_id] = len(artifacts)
            artifacts.append(addition)
            changes["new_artifacts"] += 1
    return changes


def _empty_report(total=0):
    report = {
        "playlist_items_reported": total,
        "playlist_entries_scanned": 0,
        "new_artifacts": 0,
        "metadata_updates": 0,
        "unchanged": 0,
    }
    report.update({key: 0 for key in CLASSIFICATION_KEYS})
    return report


def _add_counts(report, additions):
    for key, value in additions.items():
        report[key] = report.get(key, 0) + int(value)


def _print_report(report, total_artifacts):
    classification_total = sum(
        int(report.get(key, 0)) for key in CLASSIFICATION_KEYS
    )
    scanned = int(report.get("playlist_entries_scanned", 0))
    if classification_total != scanned:
        raise ValueError(
            "Playlist classification totals do not match entries scanned: "
            f"{classification_total} classified, {scanned} scanned."
        )
    print()
    print("=" * 55)
    print("Playlist sync summary")
    print(f"Playlist items reported by Spotify: {report['playlist_items_reported']}")
    print(f"Playlist entries scanned: {report['playlist_entries_scanned']}")
    print(f"Valid unique Spotify tracks: {report['valid_tracks']}")
    print(f"New artifacts added: {report['new_artifacts']}")
    print(f"Existing artifacts unchanged: {report['unchanged']}")
    print(f"Metadata updates: {report['metadata_updates']}")
    print(f"Duplicate occurrences skipped: {report['duplicate_tracks']}")
    print(f"Local files skipped: {report['local_files']}")
    print(f"Unavailable entries skipped: {report['unavailable_entries']}")
    print(f"Unsupported entries skipped: {report['unsupported_entries']}")
    print(f"Malformed entries skipped: {report['malformed_entries']}")
    print(f"Total artifacts preserved: {total_artifacts}")
    print("=" * 55)


def _load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as state_file:
            return json.load(state_file)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    temporary_path = STATE_PATH + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2)
    os.replace(temporary_path, STATE_PATH)


def _checkpoint(
    artifacts,
    existing,
    manifest,
    playlist_name,
    snapshot_id,
    captured_at,
    next_offset,
    total,
    report,
):
    save_manifest_checkpoint(manifest)
    path = save_checkpoint(build_collection(artifacts, existing))
    _save_state({
        "playlist_id": PLAYLIST_ID,
        "playlist_name": playlist_name,
        "in_progress_snapshot": snapshot_id,
        "captured_at": captured_at,
        "next_offset": next_offset,
        "expected_total": total,
        "report": report,
    })
    return path


def _summary_context(summary):
    """Return the fields that must remain stable throughout a complete scan."""
    return {
        "playlist_id": summary.get("playlist_id", PLAYLIST_ID),
        "name": summary.get("name", ""),
        "snapshot_id": summary.get("snapshot_id", ""),
        "total": int(summary.get("total", 0)),
    }


def _state_int(state, key, default=-1):
    try:
        return int(state.get(key, default))
    except (TypeError, ValueError):
        return default


def _scan_is_complete(report, manifest_rows, reported_total):
    """Return whether occurrence and classification accounting is complete."""
    scanned = _state_int(report, "playlist_entries_scanned")
    classification_total = sum(
        _state_int(report, key, 0) for key in CLASSIFICATION_KEYS
    )
    return (
        scanned >= 0
        and scanned == len(manifest_rows) == int(reported_total)
        and classification_total == scanned
    )


def _invalidate_incomplete_scan():
    """Discard unusable progress so the next run starts from position one."""
    remove_checkpoint()
    remove_manifest_checkpoint()
    _save_state({})


def main():
    print("=" * 45)
    print(" Music Museum Toolkit")
    print(" Version 0.3.1 Validation and Hardening")
    print("=" * 45)
    print()

    existing = load_existing_collection()
    checkpoint = load_checkpoint()
    permanent_manifest = load_manifest()
    manifest_checkpoint = load_manifest_checkpoint()
    state = _load_state()

    spotify = connect_spotify()
    try:
        summary = get_playlist_summary(spotify, PLAYLIST_ID)
    except SpotifyRateLimit as error:
        print(f"\nSpotify quota is still cooling down: {error.retry_after} seconds.")
        print("No collection files were changed.")
        return

    initial_context = _summary_context(summary)
    snapshot_id = initial_context["snapshot_id"]
    total = initial_context["total"]
    playlist_name = initial_context["name"]
    print(f'Live playlist: "{playlist_name}"')
    print(f"Spotify currently reports {total} items.")

    if (
        state.get("complete_snapshot") == snapshot_id
        and not existing.empty
        and isinstance(state.get("last_report"), dict)
    ):
        manifest_errors = validate_manifest(
            permanent_manifest,
            existing,
            PLAYLIST_ID,
            playlist_name,
            snapshot_id,
            state["last_report"],
        )
        if not manifest_errors:
            print("Playlist has not changed since the last completed sync.")
            save_collection(existing, existing)
            save_manifest(
                permanent_manifest,
                existing,
                PLAYLIST_ID,
                playlist_name,
                snapshot_id,
                state["last_report"],
            )
            _print_report(state["last_report"], len(existing))
            return
        print(
            "The completed snapshot has no valid matching playlist manifest; "
            "performing one full scan."
        )

    resume_report = state.get("report", {})
    resume_rows = _state_int(resume_report, "playlist_entries_scanned", 0)
    can_resume = (
        state.get("playlist_id") == PLAYLIST_ID
        and state.get("in_progress_snapshot") == snapshot_id
        and _state_int(state, "expected_total") == total
        and (resume_rows == 0 or not checkpoint.empty)
        and validate_manifest_checkpoint(
            manifest_checkpoint,
            PLAYLIST_ID,
            playlist_name,
            snapshot_id,
            resume_report,
        )
    )

    if can_resume:
        combined = pd.concat([existing, checkpoint], ignore_index=True)
        combined = combined.drop_duplicates("Source Track ID", keep="last")
        artifacts = _artifacts_from_collection(combined)
        manifest_rows = manifest_checkpoint.to_dict("records")
        offset = int(state.get("next_offset", 0))
        first_positions = {
            _text(row.get("Source Track ID")): int(row["Playlist Position"])
            for row in manifest_rows
            if row.get("Classification") == "valid track"
            and _text(row.get("Source Track ID"))
        }
        captured_at = (
            _text(manifest_rows[0].get("Captured At"))
            if manifest_rows
            else state.get("captured_at", "")
        )
        report = _empty_report(total)
        _add_counts(report, resume_report)
        report["playlist_items_reported"] = total
        print(f"Resuming this playlist version at item {offset + 1}.")
    else:
        combined = existing.copy()
        artifacts = _artifacts_from_collection(existing)
        manifest_rows = []
        offset = 0
        first_positions = {}
        captured_at = datetime.now(timezone.utc).isoformat()
        report = _empty_report(total)
        print("Starting a fresh scan of this playlist version.")

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    progress = tqdm(total=pages, initial=offset // PAGE_SIZE, desc="Reading playlist")
    stopped_error = None
    try:
        while offset < total:
            (
                page_artifacts,
                next_page,
                page_counts,
                scanned,
                page_manifest_rows,
            ) = get_playlist_page_occurrences(
                spotify,
                PLAYLIST_ID,
                offset,
                PAGE_SIZE,
                report["playlist_entries_scanned"] + 1,
                playlist_name,
                snapshot_id,
                captured_at,
                first_positions,
            )
            merge_counts = _merge_artifacts(artifacts, page_artifacts)
            manifest_rows.extend(page_manifest_rows)
            _add_counts(report, page_counts)
            _add_counts(report, merge_counts)
            report["playlist_entries_scanned"] += scanned
            offset += PAGE_SIZE
            _checkpoint(
                artifacts,
                existing,
                pd.DataFrame(manifest_rows, columns=MANIFEST_COLUMNS),
                playlist_name,
                snapshot_id,
                captured_at,
                offset,
                total,
                report,
            )
            progress.update(1)
            if not next_page:
                break
    except SpotifyRateLimit as error:
        stopped_error = error
    except KeyboardInterrupt:
        print("\nSync interrupted by user.")
    finally:
        progress.close()

    if stopped_error:
        hours = stopped_error.retry_after / 3600
        print(
            f"\nSpotify requested a {stopped_error.retry_after}-second "
            f"cooldown ({hours:.1f} hours)."
        )
        print("Completed pages are checkpointed; the next run resumes here.")
        print("The permanent collection was not overwritten.")
        return

    if offset < total:
        _checkpoint(
            artifacts,
            existing,
            pd.DataFrame(manifest_rows, columns=MANIFEST_COLUMNS),
            playlist_name,
            snapshot_id,
            captured_at,
            offset,
            total,
            report,
        )
        print("Progress was checkpointed; rerun to continue.")
        return

    try:
        final_summary = get_playlist_summary(spotify, PLAYLIST_ID)
    except SpotifyRateLimit as error:
        print(
            "\nAll playlist pages were checkpointed, but Spotify rate-limited "
            "the final snapshot verification."
        )
        print(
            f"Completion could not be verified ({error.retry_after}-second "
            "cooldown). No permanent outputs were replaced."
        )
        print("Rerun later to resume safely and verify completion.")
        return
    except KeyboardInterrupt:
        print(
            "\nFinal snapshot verification was interrupted. "
            "No permanent outputs were replaced."
        )
        print("Completed pages remain checkpointed; rerun to continue safely.")
        return
    except Exception as error:
        print(
            "\nFinal snapshot verification failed. "
            "No permanent outputs were replaced."
        )
        print(f"Spotify verification error: {error}")
        print("Completed pages remain checkpointed; rerun to continue safely.")
        return

    final_context = _summary_context(final_summary)
    if final_context != initial_context:
        changed_fields = [
            field
            for field in ("playlist_id", "name", "snapshot_id", "total")
            if final_context[field] != initial_context[field]
        ]
        print(
            "\nThe Spotify playlist changed during scanning "
            f"({', '.join(changed_fields)} changed)."
        )
        print("No permanent outputs were replaced and completion was not recorded.")
        print("Rerun the toolkit to start a clean scan of the new playlist snapshot.")
        return

    if not _scan_is_complete(report, manifest_rows, total):
        scanned = _state_int(report, "playlist_entries_scanned")
        classification_total = sum(
            _state_int(report, key, 0) for key in CLASSIFICATION_KEYS
        )
        print("\nSpotify returned an incomplete occurrence scan.")
        print(
            f"Reported playlist total: {total}; entries scanned: {scanned}; "
            f"manifest rows: {len(manifest_rows)}; "
            f"classified entries: {classification_total}."
        )
        print("No permanent outputs were replaced and completion was not recorded.")
        _invalidate_incomplete_scan()
        print("Partial checkpoints were invalidated; the next run will start clean.")
        return

    collection = build_collection(artifacts, combined)
    manifest = map_museum_ids(
        pd.DataFrame(manifest_rows, columns=MANIFEST_COLUMNS),
        collection,
    )
    assert_valid_collection(collection, existing)
    assert_valid_manifest(
        manifest,
        collection,
        PLAYLIST_ID,
        playlist_name,
        snapshot_id,
        report,
    )
    save_collection(collection, existing)
    save_manifest(
        manifest,
        collection,
        PLAYLIST_ID,
        playlist_name,
        snapshot_id,
        report,
    )
    remove_checkpoint()
    remove_manifest_checkpoint()
    _save_state({
        "playlist_id": PLAYLIST_ID,
        "playlist_name": playlist_name,
        "complete_snapshot": snapshot_id,
        "playlist_total": total,
        "last_report": report,
    })

    print("\nPlaylist sync complete!")
    _print_report(report, len(collection))


if __name__ == "__main__":
    main()
