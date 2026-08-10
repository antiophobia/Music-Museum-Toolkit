"""Resilient terminal Museum: import, search, inspection, and exhibits."""

import os

from collection_manager import load_existing_collection
from exhibit_manager import (
    add_curated_artifact, build_exhibit_index, create_exhibit,
    create_starter_exhibits, evaluate_automatic_exhibit, generated_album_results,
    generated_artist_results, load_exhibits, save_exhibits,
    remove_curated_artifact, reorder_exhibits,
)
from inspection_manager import (
    inspect_album, inspect_artifact, inspect_artist, listening_overview,
    search_albums, search_artifacts, search_entities,
)
from listening_archive import load_events
from manifest_manager import load_manifest
from museum_import import (
    commit_import, default_input_directory, discover_default_archives, scan_import,
)


MENU = """\
====================================================
MUSEUM
====================================================

[1] Museum Home
[2] Browse Exhibits
[3] Inspect Artifact
[4] Inspect Artist
[5] Inspect Album
[6] Listening Overview
[7] Import Museum Data
[8] Return
"""
INPUT_DISPLAY_PATH = "Input\\Spotify Data\\"


def _duration(milliseconds):
    seconds = int(milliseconds or 0) // 1000; hours, seconds = divmod(seconds, 3600); minutes, seconds = divmod(seconds, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m {seconds}s"


def _choose(items, prompt="Select: "):
    choice = input(prompt).strip()
    return items[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(items) else None


def _print_statistics(result):
    print(f'Recorded events:       {result["recorded_event_count"]}')
    if not result["recorded_event_count"]: return
    print(f'Meaningful plays:      {result["meaningful_plays"]}')
    print(f'Completed plays:       {result["completed_plays"]}')
    print(f'Explicit skips:        {result["explicit_skips"]}')
    print(f'Short plays:           {result["short_plays"]}')
    print(f'Interrupted / other:   {result["interrupted_other"]}')
    if result["total_listening_ms"] is not None:
        print(f'Listening time:        {_duration(result["total_listening_ms"])}')
    if result["average_listening_ms"] is not None:
        print(f'Average duration:      {_duration(result["average_listening_ms"])}')
    if result["average_completion"] is not None: print(f'Average completion:    {result["average_completion"]:.0%}')
    print(f'First recorded listen: {result["first_recorded_listen"]}')
    print(f'Latest recorded listen:{result["latest_recorded_listen"]}')


def _summary(values):
    return ", ".join(f"{key}: {value}" for key, value in values.items())


def _print_activity(result):
    if not any(result[key] for key in (
        "activity_by_year", "activity_by_month", "activity_by_hour"
    )):
        return
    print("\nACTIVITY")
    if result["activity_by_year"]:
        print("By year: " + _summary(result["activity_by_year"]))
    if result["activity_by_month"]:
        print("By month: " + _summary(result["activity_by_month"]))
    if result["activity_by_hour"]:
        hours = {
            f"{int(hour):02}:00": count
            for hour, count in result["activity_by_hour"].items()
        }
        print("By hour: " + _summary(hours))


def _print_listening_context(result):
    fields = (
        ("Start reasons", "start_reasons"),
        ("End reasons", "end_reasons"),
        ("Shuffle", "shuffle"),
        ("Offline/downloaded", "offline"),
        ("Device/platform", "devices"),
        ("Operating system", "operating_systems"),
        ("Country", "countries"),
    )
    if not any(result.get(key) for _, key in fields):
        return
    print("\nLISTENING CONTEXT")
    for label, key in fields:
        if result.get(key):
            print(f"{label}: {_summary(result[key])}")


def _print_home(collection, events, exhibits, manifest=None):
    if not len(collection) and not events and not exhibits:
        print("\nYour Museum has not been built yet.\n")
        print("Place your untouched Spotify data ZIPs in:")
        print(f"    {INPUT_DISPLAY_PATH}\n")
        print("Then choose [7] Import Museum Data.")
        print("No Spotify Developer credentials are required.")
        return
    print(f"\nPreserved artifacts: {len(collection)}")
    print(f"Recorded events: {len(events)}")
    print(f"Exhibits: {len(exhibits)}")
    if not events:
        print("\nListening history has not been imported yet.")
        print(f"Put Spotify ZIPs in {INPUT_DISPLAY_PATH} and choose [7].")
    featured = [item for item in exhibits if item.get("featured") and item.get("visible", True)]
    if featured:
        index = build_exhibit_index(collection, events, manifest)
        print("\nFEATURED EXHIBITS")
        shown = 0
        for exhibit in featured:
            result = evaluate_automatic_exhibit(exhibit, index, limit=3)
            if not result["rows"]:
                continue
            shown += 1
            top = result["rows"][0]
            print(f'[{exhibit["display_number"]:03}] {exhibit["title"]}')
            print(f'      Leading result: {top["title"]}')
        if shown:
            print("\nChoose [2] Browse Exhibits to open these views and inspect their results.")


def _select_artifact(collection):
    query = input("\nSearch by song, artist, album, Spotify URI, or Museum ID:\n> ").strip()
    matches = search_artifacts(collection, query)
    if not matches: print("\nNo matching preserved artifacts were found."); return None
    for index, artifact in enumerate(matches, 1):
        print(f'\n[{index}] {artifact.get("Title", "")} — {artifact.get("Artist", "")}')
        print(f'    Album: {artifact.get("Album", "") or "Unknown"}')
        print(f'    Museum ID: {artifact.get("Museum ID", "")}')
    selected = _choose(matches, "\nSelect: ")
    if selected is None: print("\nInvalid selection.")
    return selected


def inspect_artifact_flow(collection, events, manifest):
    artifact = _select_artifact(collection)
    if artifact is None: return
    _show_artifact(artifact, events, manifest)


def _show_artifact(artifact, events, manifest=None):
    result = inspect_artifact(artifact, events, manifest)
    print(f'\n{artifact.get("Title", "").upper()} — {artifact.get("Artist", "").upper()}')
    print("\nMUSEUM RECORD")
    print(f'Museum ID: {artifact.get("Museum ID", "")}')
    track_id = str(artifact.get("Source Track ID", "") or "").strip()
    if track_id:
        print(f"Spotify URI: spotify:track:{track_id}")
    duration = str(artifact.get("Duration (ms)", "") or "").strip()
    if duration.isdigit() and int(duration) >= 0:
        print(f"Duration: {_duration(int(duration))}")
    for label, key in (("Album", "Album"), ("Release date", "Release Date"),
                       ("Preserved at", "Archived At"), ("Status", "Status")):
        if artifact.get(key): print(f'{label}: {artifact[key]}')
    print("\nPLAYBACK SUMMARY")
    _print_statistics(result)
    _print_activity(result)
    _print_listening_context(result)
    if result["playlist_occurrences"]:
        print("\nPLAYLIST OCCURRENCE HISTORY")
        print(f'Playlist occurrences: {len(result["playlist_occurrences"])}')
        print(f'Duplicate occurrences: {result["duplicate_occurrences"]}')
        for occurrence in result["playlist_occurrences"][:25]:
            position = occurrence.get("Playlist Position", "?")
            classification = occurrence.get("Classification", "")
            added_at = occurrence.get("Added At", "")
            detail = f"Position {position}: {classification}"
            if added_at:
                detail += f"; added {added_at}"
            print(detail)
        if len(result["playlist_occurrences"]) > 25:
            print(
                f'... {len(result["playlist_occurrences"]) - 25} more occurrences'
            )


def _show_entity(collection, events, entity_type, title, artist=""):
    if entity_type == "artist":
        result = inspect_artist(collection, events, title)
        heading = title
    else:
        result = inspect_album(collection, events, title, artist or None)
        heading = f"{title} - {artist}" if artist else title
    print(f"\n{heading.upper()}\nPreserved artifacts: {len(result['artifacts'])}")
    _print_statistics(result)
    _print_activity(result)
    _print_listening_context(result)
    tracks = result.get("most_listened_tracks", [])
    if tracks:
        print("\nMOST-LISTENED TRACKS")
        for item in tracks[:10]:
            print(f'{item["artifact"]["Title"]}: {item["events"]} recorded events')


def _entity_flow(collection, events, field):
    query = input(f"\nSearch {field.lower()}: ").strip()
    choices = (
        search_albums(collection, query)
        if field == "Album" else search_entities(collection, field, query)
    )
    if not choices: print(f"\nNo matching preserved {field.lower()} was found."); return
    for index, value in enumerate(choices, 1):
        if field == "Album":
            print(f'[{index}] {value["album"]} — {value["artist"]} ({value["artifact_count"]} artifacts)')
        else:
            print(f"[{index}] {value}")
    selected = _choose(choices)
    if selected is None: print("\nInvalid selection."); return
    if field == "Artist":
        _show_entity(collection, events, "artist", selected)
    else:
        _show_entity(collection, events, "album", selected["album"], selected["artist"])


def _row_measure(row, metric):
    fields = {
        "most_played_tracks": ("events", "events"),
        "most_played_artists": ("events", "events"),
        "most_played_albums": ("events", "events"),
        "artist_listening_time": ("listening_ms", "recorded"),
        "artist_relationships": ("relationship_days", "days of recorded history"),
        "album_listening_time": ("listening_ms", "recorded"),
        "album_completions": ("completed", "completed plays"),
        "most_listening_time": ("listening_ms", "recorded"),
        "most_meaningful_plays": ("meaningful", "meaningful plays"),
        "most_completed_plays": ("completed", "completed plays"),
        "most_explicit_skips": ("explicit_skips", "explicit skips"),
        "most_natural_completions": ("natural_completions", "natural completions"),
        "direct_selection": ("direct_selection", "direct selections"),
        "late_night": ("late_night", "late-night events"),
        "morning_listening": ("morning", "morning events"),
        "evening_listening": ("evening", "evening events"),
        "weekend_listening": ("weekend", "weekend events"),
        "weekday_listening": ("weekday", "weekday events"),
        "mobile_listening": ("mobile", "mobile events"),
        "desktop_listening": ("desktop", "desktop events"),
        "offline_listening": ("offline", "offline events"),
        "shuffle_listening": ("shuffle", "shuffle events"),
        "most_consistent": ("distinct_months", "recorded months"),
        "longest_relationships": ("relationship_days", "days of recorded history"),
        "returned_after_gap": ("longest_gap_days", "day longest gap"),
        "longest_gaps": ("longest_gap_days", "day longest gap"),
        "playlist_mainstays": ("playlist_count", "playlists"),
        "repeated_collection": ("occurrence_count", "occurrences"),
        "longest_tracks": ("duration_ms", "duration"),
        "shortest_tracks": ("duration_ms", "duration"),
        "listening_in_year": ("period_events", "events"),
    }
    field, label = fields.get(metric, ("events", "events"))
    value = row.get(field, 0)
    if metric == "most_explicit_skips" and row.get("skip_rate") is not None:
        return f"{value:,} {label} ({row['skip_rate']:.0%} of recorded events)"
    if metric in {"most_completed_plays", "album_completions"} and row.get("completion_rate") is not None:
        return f"{value:,} {label} ({row['completion_rate']:.0%} of recorded events)"
    if field in {"listening_ms", "duration_ms"}:
        return f"{_duration(value)} {label}"
    if field in {"relationship_days", "longest_gap_days"}:
        value = round(value)
    return f"{value:,} {label}" if isinstance(value, int) else f"{value} {label}"


def _row_context(row, metric):
    recorded_time = (
        f"{_duration(row['listening_ms'])} recorded"
        if row.get("known_ms") else "recorded duration unavailable"
    )
    if metric == "most_played_tracks":
        return f"{row['meaningful']:,} meaningful plays | {recorded_time}"
    if row.get("entity_type") in {"artist", "album"}:
        return f"{row.get('artifact_count', 0):,} preserved tracks | {recorded_time}"
    if metric in {"longest_relationships", "returned_after_gap", "longest_gaps"}:
        return (
            f"{row['first_recorded_listen']} -> {row['latest_recorded_listen']} | "
            f"{row['events']:,} recorded events"
        )
    daypart_field = {
        "late_night": "late_night", "morning_listening": "morning",
        "evening_listening": "evening", "weekend_listening": "weekend",
        "weekday_listening": "weekday", "mobile_listening": "mobile",
        "desktop_listening": "desktop", "offline_listening": "offline",
        "shuffle_listening": "shuffle",
    }.get(metric)
    if daypart_field and row.get("events"):
        return f"{row[daypart_field] / row['events']:.0%} of this result's resolved recorded activity"
    if row.get("entity_type") in {"year", "month"}:
        return f"{row.get('artifact_count', 0):,} preserved tracks | {recorded_time}"
    if metric in {"most_listening_time", "most_completed_plays", "most_explicit_skips",
                  "most_natural_completions", "direct_selection", "most_consistent"}:
        return f"{row['events']:,} recorded events | {recorded_time}"
    if metric in {"oldest_releases", "newest_releases"}:
        return f"Release date: {row.get('release_date', '')}"
    if metric in {"playlist_mainstays", "repeated_collection"}:
        return f"{row.get('playlist_count', 0):,} preserved playlists | {row.get('occurrence_count', 0):,} occurrences"
    return ""


def _navigate_exhibit_row(row, collection, events, manifest, index):
    entity_type = row.get("entity_type")
    if entity_type == "artifact":
        _show_artifact(row["artifact"], events, manifest)
    elif entity_type == "artist":
        _show_entity(collection, events, "artist", row["title"])
    elif entity_type == "album":
        _show_entity(collection, events, "album", row["title"], row.get("artist", ""))
    elif entity_type in {"year", "month"}:
        period = row["entity_id"]
        print(f"\n{row['title'].upper()} — {row['events']} recorded events")
        print(f"Preserved artifacts represented: {row.get('artifact_count', 0)}")
        matching = []
        for museum_id, stat in index["track_stats"].items():
            count = stat["years"].get(period, 0) if entity_type == "year" else stat["months"].get(period, 0)
            if count:
                artifact = index["artifacts"][museum_id]
                matching.append((count, str(artifact.get("Title", "")), str(artifact.get("Artist", ""))))
        for number, (count, title, artist) in enumerate(sorted(matching, reverse=True)[:25], 1):
            print(f"{number:02}. {title} — {artist}: {count} events")


def _open_exhibit(selected, collection, events, exhibits, manifest, index):
    print(f'\n{selected["title"].upper()}\n{selected["description"]}')
    if selected["type"] == "automatic":
        result = evaluate_automatic_exhibit(selected, index)
        if not result["rows"]:
            print("No supported data is available for this exhibit.")
            return exhibits
        metric = selected.get("rule", {}).get("metric")
        for number, row in enumerate(result["rows"], 1):
            byline = f' — {row.get("artist", "")}' if row.get("artist") and row.get("artist") != row["title"] else ""
            print(f'{number:02}. {row["title"]}{byline}: {_row_measure(row, metric)}')
            context = _row_context(row, metric)
            if context:
                print(f"    {context}")
        print("\nQUICK STORY")
        for sentence in result["story"]:
            print(f"- {sentence}")
        coverage = result["coverage"]
        print(
            f"\nCoverage: {coverage['resolved_events']:,} of "
            f"{coverage['total_events']:,} recorded events resolve to preserved artifacts."
        )
        if coverage["source_field"]:
            print(
                f"Source-field coverage: {coverage['source_field_events']:,} of "
                f"{coverage['resolved_events']:,} resolved events contain "
                f"{coverage['source_field'].replace('_', ' ')}."
            )
        if metric in {"most_explicit_skips", "most_completed_plays"}:
            print(f"Rates appear only with at least {coverage['minimum_rate_sample']} recorded events.")
        choice = input("\nOpen a result number, or press Enter to return: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(result["rows"]):
            _navigate_exhibit_row(result["rows"][int(choice) - 1], collection, events, manifest, index)
        return exhibits
    if selected["type"] == "generated":
        result = generated_artist_results(selected, collection, events)
        if result is None:
            result = generated_album_results(selected, collection, events)
        if result:
            _print_statistics(result)
        return exhibits
    by_id = {row["Museum ID"]: row for row in collection.to_dict("records")}
    if not selected["artifact_ids"]:
        print("This curated exhibit is empty.")
    for number, museum_id in enumerate(selected["artifact_ids"], 1):
        artifact = by_id.get(museum_id, {})
        print(f'{number:02}. {artifact.get("Title", museum_id)} — {artifact.get("Artist", "")}')
    print("\n[1] Add artifact\n[2] Remove artifact\n[3] Return")
    action = input("Select: ").strip()
    updated = selected
    if action == "1":
        artifact = _select_artifact(collection)
        if artifact:
            updated = add_curated_artifact(selected, artifact["Museum ID"])
    elif action == "2" and selected["artifact_ids"]:
        removal = _choose(selected["artifact_ids"], "Artifact number to remove: ")
        if removal:
            updated = remove_curated_artifact(selected, removal)
    if updated is not selected:
        exhibits = [updated if item["exhibit_id"] == updated["exhibit_id"] else item for item in exhibits]
        save_exhibits(exhibits)
        print("Curated exhibit saved.")
    return exhibits


def _browse_exhibits(collection, events, exhibits, manifest=None):
    if not exhibits:
        print("\nNo supported automatic or saved exhibits exist yet.")
        print("[M] Manage Exhibits")
        print("[0] Return")
        if input("Select: ").strip().casefold() == "m":
            return _manage_exhibits(collection, exhibits)
        return exhibits
    visible = [item for item in exhibits if item.get("visible", True)]
    index = build_exhibit_index(collection, events, manifest)
    category_order = [
        "Featured", "Listening", "Artists", "Albums", "Time", "Behavior",
        "Devices & Context", "Preservation", "Generated", "Curated",
    ]
    print("\nBROWSE EXHIBITS")
    for category in category_order:
        grouped = [item for item in visible if item.get("category") == category]
        if not grouped:
            continue
        print(f"\n{category.upper()}")
        for item in grouped:
            print(f'{item["display_number"]:03}  {item["title"]:<35} {item["type"].title()}')
    print("\n[M] Manage Exhibits")
    print("[0] Return")
    raw = input("\nEnter an exhibit number or title: ").strip()
    if not raw or raw == "0":
        return exhibits
    if raw.casefold() == "m":
        return _manage_exhibits(collection, exhibits)
    selected = next((item for item in visible if str(item["display_number"]) == raw), None)
    if selected is None:
        selected = next((item for item in visible if item["title"].casefold() == raw.casefold()), None)
    if selected is None:
        print("\nNo matching exhibit was found.")
        return exhibits
    return _open_exhibit(selected, collection, events, exhibits, manifest, index)


def _manage_exhibits(collection, exhibits):
    print("\nMANAGE EXHIBITS")
    print("[1] Create curated exhibit")
    print("[2] Reorder exhibit display")
    print("[3] Return")
    action = input("Select: ").strip()
    if action == "1":
        return _create_curated(collection, exhibits)
    if action == "2":
        return _reorder_exhibits(exhibits)
    return exhibits


def _create_curated(collection, exhibits):
    title = input("\nCurated exhibit title: ").strip()
    if not title: print("\nExhibit creation cancelled."); return exhibits
    exhibit = create_exhibit(title, "curated", exhibits=exhibits)
    while True:
        answer = input("Add an artifact now? [Y/N]: ").strip().lower()
        if answer != "y": break
        artifact = _select_artifact(collection)
        if artifact: exhibit = add_curated_artifact(exhibit, artifact["Museum ID"])
    result = list(exhibits) + [exhibit]; save_exhibits(result); print(f"\nCreated exhibit {exhibit['display_number']:03}.")
    return result


def _reorder_exhibits(exhibits):
    if len(exhibits) < 2:
        print("\nAt least two exhibits are required for reordering.")
        return exhibits
    for item in exhibits:
        print(f'{item["display_number"]:03}  {item["title"]}')
    raw = input(
        "\nEnter every display number in the desired order, separated by commas:\n> "
    ).strip()
    try:
        numbers = [int(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError:
        print("\nInvalid exhibit order.")
        return exhibits
    by_number = {item["display_number"]: item["exhibit_id"] for item in exhibits}
    if len(numbers) != len(exhibits) or set(numbers) != set(by_number):
        print("\nThe order must include every display number exactly once.")
        return exhibits
    reordered = reorder_exhibits(exhibits, [by_number[number] for number in numbers])
    save_exhibits(reordered)
    print("\nExhibit display order saved.")
    return reordered


def _print_scan_progress(event, **details):
    """Render plain, basename-only scan progress that is safe in Windows CMD."""
    if event == "archive_started":
        print(
            f"[{details['archive_index']}/{details['archives_total']}] "
            f"{details['archive_name']}"
        )
        print("      Reading archive...")
    elif event == "archive_members":
        print(f"      JSON files found: {details['json_members_total']:,}")
    elif event == "member_started":
        print(
            f"      [{details['member_index']}/{details['member_total']}] "
            f"{details['member_name']}"
        )
        print("            Reading JSON...")
    elif event == "member_ready":
        print(f"            Records found: {details['records_total']:,}")
    elif event == "batch_complete":
        print(f"\n            Batch {details['batch_number']}/{details['batch_total']}")
        print(
            f"            Records processed: {details['records_processed']:,} / "
            f"{details['records_total']:,}"
        )
        print(
            f"            Playback records:  "
            f"{details['playback_records_found']:,}"
        )
        print(f"            Resolved:          {details['resolved']:,}")
        print(f"            Unresolved:        {details['unresolved']:,}")
        print(f"            Ambiguous:         {details['ambiguous']:,}")
    elif event == "member_complete":
        if details["member_total"] is not None:
            print(
                f"      JSON files processed: {details['member_index']:,} / "
                f"{details['member_total']:,}"
            )
        else:
            print("      JSON file processed.")
        print(
            f"      Playback records found: "
            f"{details['playback_records_found']:,}"
        )
        if details["technical_telemetry_ignored"]:
            print(
                f"      Technical telemetry ignored: "
                f"{details['technical_telemetry_ignored']:,}"
            )
    elif event == "member_failed":
        print(f"            Could not scan member safely: {details['member_name']}")
    elif event == "archive_failed":
        print("      Could not scan this archive safely.")
    elif event == "json_source_started":
        print(
            f"[{details['source_index']}/{details['sources_total']}] "
            f"{details['source_name']}"
        )
        print("      Reading JSON...")
    elif event == "json_source_failed":
        print(f"      Could not scan JSON safely: {details['source_name']}")


def import_museum_data_flow(collection):
    archives = discover_default_archives()
    source = None
    print("\nMUSEUM DATA IMPORT")
    if archives:
        print("\nSpotify archives detected:\n")
        for index, path in enumerate(archives, 1):
            print(f"[{index}] {path.rsplit(os.sep, 1)[-1]}")
        if input("\nScan detected archives? [Y/N]: ").strip().lower() == "y":
            source = archives
    else:
        print("\nNo Spotify ZIP archives were found.")
        print("\nPlace your untouched Spotify ZIPs in:")
        print(f"    {INPUT_DISPLAY_PATH}")
        print("\nThen return here and choose Import Museum Data again.")
    if source is None:
        source = input(
            "\nAdvanced: enter a Spotify ZIP, JSON file, or extracted folder "
            "path.\nPress Enter to return:\n> "
        ).strip().strip('"')
        if not source:
            print("\nImport cancelled. No Museum data changed.")
            return None
    requested = source if isinstance(source, (list, tuple)) else [source]
    archive_scan = bool(requested) and all(
        str(path).lower().endswith(".zip") for path in requested
    )
    print(
        "\nScanning Spotify archives...\n"
        if archive_scan else "\nScanning Spotify data...\n"
    )
    try: preview = scan_import(source, collection, progress=_print_scan_progress)
    except ValueError as error: print(f"\nImport scan failed safely: {error}"); return None
    print("\nScan complete.")
    print("\nMUSEUM DATA IMPORT — SCAN ONLY\n")
    for label, key in (("Files recognized", "files_recognized"),
                       ("Playback records found", "playback_events"),
                       ("Rich playback records", "rich_playback"),
                       ("Exact URI records", "events_with_uri"),
                       ("Title/artist-only records", "title_artist_only"),
                       ("Already imported", "already_imported"),
                       ("Resolved", "resolved"),
                       ("Unresolved", "unresolved"),
                       ("Ambiguous", "ambiguous"),
                       ("Malformed", "malformed"),
                       ("Technical telemetry ignored", "technical_telemetry_ignored"),
                       ("Exact title/artist matches", "exact_title_artist")):
        print(f"{label + ':':30} {preview.get(key, 0)}")
    if not preview["playback_events"]: print("\nNothing importable was found."); return None
    if input("\nProceed with permanent import? [Y/N]: ").strip().lower() != "y": print("\nImport cancelled. No Museum data changed."); return None
    try: result = commit_import(preview, collection)
    except (OSError, ValueError) as error: print(f"\nImport failed safely: {error}"); return None
    print(f"\nImported {result['added']} new events; {result['already_imported']} were already present.")
    return result


def main():
    try:
        collection = load_existing_collection(); events = load_events(); exhibits = load_exhibits()
        try: manifest = load_manifest()
        except (OSError, ValueError): manifest = None
        if events:
            refreshed = create_starter_exhibits(events, exhibits, collection, manifest)
            if refreshed != exhibits:
                save_exhibits(refreshed)
                exhibits = refreshed
    except (OSError, ValueError) as error:
        print(f"\nMuseum data cannot be opened safely: {error}"); return
    while True:
        print(MENU)
        try:
            choice = input("Select an option: ").strip()
            if choice == "1":
                _print_home(collection, events, exhibits, manifest)
            elif choice == "2":
                exhibits = _browse_exhibits(collection, events, exhibits, manifest)
            elif choice == "3": inspect_artifact_flow(collection, events, manifest)
            elif choice == "4": _entity_flow(collection, events, "Artist")
            elif choice == "5": _entity_flow(collection, events, "Album")
            elif choice == "6":
                print("\nLISTENING OVERVIEW")
                result = listening_overview(collection, events)
                _print_statistics(result)
                _print_activity(result)
                _print_listening_context(result)
            elif choice == "7":
                if import_museum_data_flow(collection):
                    events = load_events()
                    exhibits = create_starter_exhibits(events, exhibits, collection, manifest)
                    save_exhibits(exhibits)
            elif choice == "8": return
            else: print("\nInvalid selection. Please choose 1 through 8.\n")
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to Music Museum Toolkit.")
            return
        except (OSError, ValueError) as error:
            print(f"\nMuseum operation stopped safely: {error}")
