"""
Music Museum Toolkit
Version 0.3.1 - Validation and hardening
"""

import json
import os

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
from spotify_api import (
    CLASSIFICATION_KEYS,
    SpotifyRateLimit,
    connect_spotify,
    get_playlist_page,
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
    artifacts, existing, snapshot_id, next_offset, total, report, seen_track_ids
):
    path = save_checkpoint(build_collection(artifacts, existing))
    _save_state({
        "playlist_id": PLAYLIST_ID,
        "in_progress_snapshot": snapshot_id,
        "next_offset": next_offset,
        "expected_total": total,
        "report": report,
        "seen_track_ids": sorted(seen_track_ids),
    })
    return path


def main():
    print("=" * 45)
    print(" Music Museum Toolkit")
    print(" Version 0.3.1 Validation and Hardening")
    print("=" * 45)
    print()

    existing = load_existing_collection()
    checkpoint = load_checkpoint()
    state = _load_state()

    # Checkpoint rows are newer than permanent rows.
    combined = existing.copy()
    if not checkpoint.empty:
        import pandas as pd
        combined = pd.concat([existing, checkpoint], ignore_index=True)
        combined = combined.drop_duplicates("Source Track ID", keep="last")
    artifacts = _artifacts_from_collection(combined)

    spotify = connect_spotify()
    try:
        summary = get_playlist_summary(spotify, PLAYLIST_ID)
    except SpotifyRateLimit as error:
        print(f"\nSpotify quota is still cooling down: {error.retry_after} seconds.")
        print("No collection files were changed.")
        return

    snapshot_id = summary["snapshot_id"]
    total = summary["total"]
    print(f'Live playlist: "{summary["name"]}"')
    print(f"Spotify currently reports {total} items.")

    if (
        state.get("complete_snapshot") == snapshot_id
        and not existing.empty
        and isinstance(state.get("last_report"), dict)
    ):
        print("Playlist has not changed since the last completed sync.")
        save_collection(existing, existing)
        _print_report(state["last_report"], len(existing))
        return

    if state.get("in_progress_snapshot") == snapshot_id:
        offset = int(state.get("next_offset", 0))
        seen_track_ids = set(state.get("seen_track_ids", []))
        report = _empty_report(total)
        _add_counts(report, state.get("report", {}))
        report["playlist_items_reported"] = total
        print(f"Resuming this playlist version at item {offset + 1}.")
    else:
        offset = 0
        seen_track_ids = set()
        report = _empty_report(total)
        # A changed playlist invalidates the page position, but permanent
        # collection data remains reusable and is never discarded.
        if not checkpoint.empty:
            artifacts = _artifacts_from_collection(existing)
        print("Starting a fresh scan of this playlist version.")

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    progress = tqdm(total=pages, initial=offset // PAGE_SIZE, desc="Reading playlist")
    stopped_error = None
    try:
        while offset < total:
            page_artifacts, next_page, page_counts, scanned = get_playlist_page(
                spotify, PLAYLIST_ID, offset, PAGE_SIZE, seen_track_ids
            )
            merge_counts = _merge_artifacts(artifacts, page_artifacts)
            _add_counts(report, page_counts)
            _add_counts(report, merge_counts)
            report["playlist_entries_scanned"] += scanned
            offset += PAGE_SIZE
            _checkpoint(
                artifacts, existing, snapshot_id, offset, total,
                report, seen_track_ids
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
            artifacts, existing, snapshot_id, offset, total,
            report, seen_track_ids
        )
        print("Progress was checkpointed; rerun to continue.")
        return

    collection = build_collection(artifacts, combined)
    assert_valid_collection(collection, existing)
    save_collection(collection, existing)
    remove_checkpoint()
    _save_state({
        "playlist_id": PLAYLIST_ID,
        "complete_snapshot": snapshot_id,
        "playlist_total": total,
        "last_report": report,
    })

    print("\nPlaylist sync complete!")
    _print_report(report, len(collection))


if __name__ == "__main__":
    main()
