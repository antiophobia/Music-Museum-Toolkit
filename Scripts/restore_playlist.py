"""Guided, resumable restoration of the latest completed playlist manifest."""

import time
from contextlib import suppress

from spotipy.exceptions import SpotifyException

from collection_manager import load_existing_collection
from manifest_manager import load_manifest
from restoration_manager import (
    MAX_BATCH_SIZE,
    batches,
    build_report,
    build_restoration_plan,
    create_initial_state,
    exact_prefix_length,
    load_report,
    load_restoration_state,
    load_sync_state,
    mark_report_failed,
    new_run_id,
    report_path_for_run,
    restoration_description,
    save_report,
    save_restoration_state,
    update_report,
    validate_restoration_bundle,
    validate_state_for_plan,
    verify_complete,
)
from spotify_api import (
    SpotifyRateLimit,
    add_restoration_items,
    change_restoration_playlist_visibility,
    connect_spotify_restoration,
    create_restoration_playlist,
    find_restoration_playlists,
    get_current_user_identity,
    get_destination_playlist,
)

VISIBILITY_VERIFICATION_ATTEMPTS = 3
VISIBILITY_VERIFICATION_DELAY_SECONDS = 1


class CreationOutcomeUncertain(RuntimeError):
    """Creation may have succeeded, but no unique destination is yet provable."""


def _is_deterministic_spotify_failure(error):
    return error.http_status in {400, 401, 403, 404}


def _print_plan(plan):
    counts = plan["classification_counts"]
    print(f'\nPreserved snapshot:\n"{plan["source_playlist_name"]}"\n')
    print(f'Manifest occurrences: {plan["manifest_occurrences"]}')
    print(f'Ready to restore: {plan["ready_count"]}')
    print(f'Not included: {plan["excluded_count"]}\n')
    print(f'Local files: {counts["local file"]}')
    print(f'Unavailable entries: {counts["unavailable entry"]}')
    print(f'Unsupported entries: {counts["unsupported entry"]}')
    print(f'Malformed entries: {counts["malformed entry"]}')


def _show_excluded(plan):
    if not plan["excluded"]:
        print("\nThere are no nonrestorable occurrences.")
        return
    print("\nOccurrences that cannot be restored:")
    for item in plan["excluded"]:
        title = item["Title"] or "(no title)"
        print(
            f'{item["Playlist Position"]}: {title} — '
            f'{item["Classification"]}: {item["Reason"]}'
        )


def _confirm_new_run(plan):
    view = input("\nView the nonrestorable list? [Y/N]: ").strip().lower()
    if view == "y":
        _show_excluded(plan)
    print("\nReady for playlist creation.\n")
    name = input("Enter playlist name:\n> ").strip()
    if not name:
        print("\nRestoration cancelled.")
        return None

    print("\nChoose playlist visibility:\n")
    print("[1] Private (Recommended)")
    print("[2] Public")
    print("[3] Cancel")
    visibility = input("\nSelect an option: ").strip()
    if visibility == "3":
        print("\nRestoration cancelled.")
        return None
    if visibility not in {"1", "2"}:
        print("\nInvalid visibility selection. Restoration cancelled.")
        return None
    public = visibility == "2"
    label = "public" if public else "private"
    print(f'\nCreate a {label} Spotify playlist named\n"{name}"\n')
    print(f'Items to add: {plan["ready_count"]}')
    print(f'Items not included: {plan["excluded_count"]}')
    print(f'Batches required: {plan["batch_count"]}')
    confirmed = input("\n[Y] Create playlist\n[N] Cancel\n\n> ").strip().lower()
    if confirmed != "y":
        print("\nRestoration cancelled. Spotify was not contacted.")
        return None
    return name, public


def _playlist_fields(item):
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "url": (item.get("external_urls") or {}).get("spotify", ""),
        "snapshot_id": item.get("snapshot_id", ""),
        "owner_id": (item.get("owner") or {}).get("id", ""),
        "public": item.get("public"),
        "collaborative": item.get("collaborative"),
        "description": item.get("description", ""),
    }


def _adopt_destination(state, playlist, owner_id):
    fields = _playlist_fields(playlist)
    if not fields["id"] or not fields["url"] or fields["owner_id"] != owner_id:
        raise ValueError("Recovered playlist identity or ownership is invalid.")
    if fields["name"] != state["destination_playlist_name"]:
        raise ValueError("Recovered playlist name does not match the confirmed name.")
    if fields["collaborative"] is not False:
        raise ValueError("Recovered playlist unexpectedly is collaborative.")
    state.update({
        "destination_playlist_id": fields["id"],
        "destination_playlist_url": fields["url"],
        "destination_owner_id": fields["owner_id"],
        "last_returned_destination_snapshot_id": fields["snapshot_id"],
        "status": "created",
    })
    return save_restoration_state(state)


def _uncertain_creation_result(spotify, state, owner_id, original_error):
    state["status"] = "creation_uncertain"
    state = save_restoration_state(state)
    try:
        matches = find_restoration_playlists(spotify, state["run_id"])
    except Exception as search_error:
        raise CreationOutcomeUncertain(
            "Playlist creation was uncertain and recovery search could not "
            "complete. No second playlist was created."
        ) from search_error
    if len(matches) == 1:
        return _adopt_destination(state, matches[0], owner_id)
    if len(matches) > 1:
        raise ValueError(
            "Playlist creation was uncertain and multiple run-ID matches exist. "
            "Manual review is required."
        )
    raise CreationOutcomeUncertain(
        "Playlist creation was uncertain and no matching playlist is visible. "
        "No second creation request was submitted."
    ) from original_error


def _ensure_destination(
    spotify,
    state,
    owner_id,
    allow_uncertain_retry=False,
):
    if state.get("destination_playlist_id"):
        return state
    if state.get("status") in {"creating", "creation_uncertain"}:
        matches = find_restoration_playlists(spotify, state["run_id"])
        if len(matches) > 1:
            raise ValueError(
                "Multiple playlists contain this restoration run ID; user review "
                "is required before continuing."
            )
        if len(matches) == 1:
            return _adopt_destination(state, matches[0], owner_id)
        if not allow_uncertain_retry:
            raise CreationOutcomeUncertain(
                "An earlier creation request is unresolved. Explicit confirmation "
                "is required before another creation request."
            )

    state["status"] = "creating"
    state = save_restoration_state(state)
    try:
        created = create_restoration_playlist(
            spotify,
            state["destination_playlist_name"],
            state["destination_visibility"] == "public",
            restoration_description(state["run_id"]),
        )
    except SpotifyRateLimit:
        state["status"] = "creation_blocked"
        save_restoration_state(state)
        raise
    except KeyboardInterrupt:
        state["status"] = "creation_uncertain"
        save_restoration_state(state)
        raise
    except (TypeError, ValueError):
        state["status"] = "creation_blocked"
        save_restoration_state(state)
        raise
    except SpotifyException as error:
        if _is_deterministic_spotify_failure(error):
            state["status"] = "creation_blocked"
            save_restoration_state(state)
            raise
        return _uncertain_creation_result(
            spotify, state, owner_id, error
        )
    except Exception as error:
        return _uncertain_creation_result(
            spotify, state, owner_id, error
        )
    return _adopt_destination(state, created, owner_id)


def _resolve_uncertain_creation(spotify, state, owner_id):
    """Require separate user consent before retrying an unresolved creation."""
    while True:
        matches = find_restoration_playlists(spotify, state["run_id"])
        if len(matches) == 1:
            return _adopt_destination(state, matches[0], owner_id)
        if len(matches) > 1:
            raise ValueError(
                "Multiple playlists contain this restoration run ID; manual "
                "review is required."
            )
        state["status"] = "creation_uncertain"
        state = save_restoration_state(state)
        print(
            "\nSpotify may have received the earlier creation request, but no "
            "matching\nplaylist is currently visible.\n"
        )
        print("Check your Spotify account before retrying.\n")
        print("[1] Search again")
        print("[2] I confirmed no playlist exists -- retry creation")
        print("[3] Cancel")
        choice = input("\nSelect an option: ").strip()
        if choice == "1":
            continue
        if choice == "2":
            return _ensure_destination(
                spotify,
                state,
                owner_id,
                allow_uncertain_retry=True,
            )
        if choice == "3":
            return None
        print("\nInvalid selection. Please choose 1, 2, or 3.")


def _has_exact_run_marker(description, run_id):
    marker = f"Restoration run: {run_id}"
    return isinstance(description, str) and description.rstrip().endswith(marker)


def _validate_destination_identity(destination, state, owner_id):
    if destination["playlist_id"] != state["destination_playlist_id"]:
        raise ValueError("Destination playlist identity changed.")
    if destination["name"] != state["destination_playlist_name"]:
        raise ValueError("Destination playlist name changed.")
    if destination["owner_id"] != owner_id:
        raise ValueError("Destination playlist is no longer owned by this account.")
    if state.get("destination_owner_id") != owner_id:
        raise ValueError(
            "Restoration state owner does not match the authenticated account."
        )
    if destination["collaborative"] is not False:
        raise ValueError("Destination playlist unexpectedly became collaborative.")
    if not _has_exact_run_marker(
        destination.get("description"), state["run_id"]
    ):
        raise ValueError(
            "Destination playlist no longer contains the exact restoration run "
            "marker."
        )
    return True


def _validate_destination_visibility(destination, state):
    expected_public = state["destination_visibility"] == "public"
    if destination.get("public") is not expected_public:
        raise ValueError("Destination playlist visibility changed.")
    return True


def _validate_destination(destination, state, owner_id):
    _validate_destination_identity(destination, state, owner_id)
    _validate_destination_visibility(destination, state)
    return True


def _enforce_destination_visibility(
    spotify,
    state,
    report_rows,
    plan,
    owner_id,
):
    """Verify one run-bound destination and enforce its requested visibility."""
    validate_restoration_bundle(state, report_rows, plan)
    destination = get_destination_playlist(
        spotify, state["destination_playlist_id"]
    )
    _validate_destination_identity(destination, state, owner_id)
    expected_public = state["destination_visibility"] == "public"
    if destination.get("public") is expected_public:
        return destination

    change_restoration_playlist_visibility(
        spotify,
        state["destination_playlist_id"],
        expected_public,
    )
    for attempt in range(VISIBILITY_VERIFICATION_ATTEMPTS):
        if attempt:
            time.sleep(VISIBILITY_VERIFICATION_DELAY_SECONDS)
        destination = get_destination_playlist(
            spotify, state["destination_playlist_id"]
        )
        _validate_destination_identity(destination, state, owner_id)
        if destination.get("public") is expected_public:
            return destination

    label = "public" if expected_public else "private"
    raise ValueError(
        f"Destination playlist visibility could not be verified as {label}."
    )


def _checkpoint_confirmation(
    state,
    report_rows,
    snapshot_id,
    confirmed_length,
):
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError("Spotify did not return a usable destination snapshot ID.")
    state["last_confirmed_destination_length"] = confirmed_length
    state["last_returned_destination_snapshot_id"] = snapshot_id
    state["status"] = "in_progress"
    state = save_restoration_state(state)
    update_report(report_rows, state, confirmed_length)
    save_report(report_rows, state["report_path"])
    return state


def _block_attempt(state, report_rows, confirmed, batch, reason):
    state["status"] = "blocked"
    state = save_restoration_state(state)
    mark_report_failed(
        report_rows,
        confirmed + 1,
        len(batch),
        reason,
    )
    save_report(report_rows, state["report_path"])
    return state


def _reconcile_ambiguous_add(
    spotify,
    state,
    report_rows,
    owner_id,
    planned,
    confirmed,
    batch,
    original_error,
):
    try:
        destination = get_destination_playlist(
            spotify, state["destination_playlist_id"]
        )
        _validate_destination(destination, state, owner_id)
        remote_length = exact_prefix_length(destination["uris"], planned)
    except Exception:
        _block_attempt(
            state,
            report_rows,
            confirmed,
            batch,
            "The attempted add could not be reconciled safely.",
        )
        raise
    if remote_length == confirmed:
        _block_attempt(
            state,
            report_rows,
            confirmed,
            batch,
            "The attempted add was not confirmed by remote reconciliation.",
        )
        raise original_error
    if remote_length != confirmed + len(batch):
        _block_attempt(
            state,
            report_rows,
            confirmed,
            batch,
            "The attempted add did not reconcile to one exact batch.",
        )
        raise ValueError(
            "Ambiguous add result did not reconcile to one exact batch."
        )
    state = _checkpoint_confirmation(
        state,
        report_rows,
        destination["snapshot_id"],
        remote_length,
    )
    return state, remote_length


def _restore_batches(spotify, state, report_rows, owner_id):
    planned = list(state["planned_uris"])
    destination = get_destination_playlist(
        spotify, state["destination_playlist_id"]
    )
    _validate_destination(destination, state, owner_id)
    confirmed = exact_prefix_length(destination["uris"], planned)
    state = _checkpoint_confirmation(
        state,
        report_rows,
        destination["snapshot_id"],
        confirmed,
    )

    while confirmed < len(planned):
        batch = planned[confirmed:confirmed + MAX_BATCH_SIZE]
        try:
            response = add_restoration_items(
                spotify,
                state["destination_playlist_id"],
                batch,
                position=confirmed,
            )
        except SpotifyRateLimit:
            save_restoration_state(state)
            save_report(report_rows, state["report_path"])
            raise
        except SpotifyException as error:
            if _is_deterministic_spotify_failure(error):
                _block_attempt(
                    state,
                    report_rows,
                    confirmed,
                    batch,
                    "Spotify rejected the add request.",
                )
                raise
            state, confirmed = _reconcile_ambiguous_add(
                spotify,
                state,
                report_rows,
                owner_id,
                planned,
                confirmed,
                batch,
                error,
            )
            continue
        except Exception as error:
            state, confirmed = _reconcile_ambiguous_add(
                spotify,
                state,
                report_rows,
                owner_id,
                planned,
                confirmed,
                batch,
                error,
            )
            continue

        snapshot_id = (
            response.get("snapshot_id", "")
            if isinstance(response, dict)
            else ""
        )
        if snapshot_id:
            confirmed += len(batch)
            state = _checkpoint_confirmation(
                state,
                report_rows,
                snapshot_id,
                confirmed,
            )
            continue

        state, confirmed = _reconcile_ambiguous_add(
            spotify,
            state,
            report_rows,
            owner_id,
            planned,
            confirmed,
            batch,
            ValueError(
                "Spotify's add response lacked a usable snapshot ID."
            ),
        )

    destination = get_destination_playlist(
        spotify, state["destination_playlist_id"]
    )
    _validate_destination(destination, state, owner_id)
    verify_complete(destination["uris"], planned)
    state["last_confirmed_destination_length"] = len(planned)
    state["last_returned_destination_snapshot_id"] = destination["snapshot_id"]
    state["status"] = "complete"
    state = save_restoration_state(state)
    update_report(report_rows, state, len(planned))
    save_report(report_rows, state["report_path"])
    return state


def _restore_verified_destination(
    spotify,
    state,
    report_rows,
    plan,
    owner_id,
):
    _enforce_destination_visibility(
        spotify,
        state,
        report_rows,
        plan,
        owner_id,
    )
    return _restore_batches(
        spotify,
        state,
        report_rows,
        owner_id,
    )


def main():
    print("=" * 55)
    print(" Playlist Restoration")
    print("=" * 55)
    print("\nLoading preserved Collection and playlist manifest...")
    state = {}
    try:
        collection = load_existing_collection()
        manifest = load_manifest()
        sync_state = load_sync_state()
        plan = build_restoration_plan(collection, manifest, sync_state)
        state = load_restoration_state()
        in_progress = validate_state_for_plan(state, plan)
        if in_progress:
            report_rows = load_report(state["report_path"])
            validate_restoration_bundle(state, report_rows, plan)
    except (OSError, ValueError) as error:
        print(f"\nRestoration cannot start: {error}")
        return

    _print_plan(plan)
    if in_progress:
        print("\nIncomplete restoration found:\n")
        print(f'Playlist: {state.get("destination_playlist_name", "")}')
        print(
            "Confirmed items: "
            f'{state.get("last_confirmed_destination_length", 0)} / '
            f'{state.get("total_planned_item_count", 0)}'
        )
        print(f'Visibility: {state.get("destination_visibility", "")}\n')
        print("[1] Resume restoration")
        print("[2] Cancel")
        try:
            resume_choice = input("\nSelect an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nRestoration cancelled.")
            return
        if resume_choice != "1":
            print("\nRestoration cancelled.")
            return
        public = state["destination_visibility"] == "public"
    else:
        try:
            choice = _confirm_new_run(plan)
        except (EOFError, KeyboardInterrupt):
            print("\nRestoration cancelled. Spotify was not contacted.")
            return
        if choice is None:
            return
        name, public = choice
        run_id = new_run_id()
        report_path = report_path_for_run(run_id)
        state = create_initial_state(
            plan, run_id, name, public, report_path
        )
        report_rows = build_report(plan, run_id)
        try:
            save_report(report_rows, report_path)
            state = save_restoration_state(state)
            validate_restoration_bundle(state, report_rows, plan)
        except OSError as error:
            print(f"\nRestoration cannot begin because local state failed: {error}")
            return
        except ValueError as error:
            print(f"\nRestoration cannot begin because local state is invalid: {error}")
            return

    try:
        spotify = connect_spotify_restoration(public=public)
        identity = get_current_user_identity(spotify)
        if not identity["id"]:
            raise ValueError("Spotify did not return the signed-in account identity.")
        print(
            "Restoration authorization successful! "
            f'Signed in as {identity["name"]}.'
        )
        if (
            not state.get("destination_playlist_id")
            and state.get("status") in {"creating", "creation_uncertain"}
        ):
            state = _resolve_uncertain_creation(
                spotify, state, identity["id"]
            )
            if state is None:
                print("\nRestoration remains paused. No playlist was created.")
                return
        else:
            state = _ensure_destination(spotify, state, identity["id"])
        update_report(report_rows, state)
        save_report(report_rows, state["report_path"])
        state = _restore_verified_destination(
            spotify,
            state,
            report_rows,
            plan,
            identity["id"],
        )
    except KeyboardInterrupt:
        print("\nRestoration paused safely.")
        if state.get("destination_playlist_url"):
            print(f'Partial playlist: {state["destination_playlist_url"]}')
        return
    except SpotifyRateLimit as error:
        print(
            f"\nSpotify requested a {error.retry_after}-second cooldown. "
            "Restoration progress was retained."
        )
        return
    except Exception as error:
        print(f"\nRestoration stopped safely: {error}")
        if state.get("destination_playlist_url"):
            print(f'Recoverable playlist: {state["destination_playlist_url"]}')
        return

    print("\nRestoration complete.\n")
    print(f'Playlist:\n{state["destination_playlist_name"]}\n')
    print(f'Spotify URL:\n{state["destination_playlist_url"]}\n')
    print(f'Manifest occurrences: {plan["manifest_occurrences"]}')
    print(f'Items restored: {plan["ready_count"]}')
    print(f'Items not included: {plan["excluded_count"]}\n')
    print(f'Restoration report:\n{state["report_path"]}')
    with suppress(EOFError, KeyboardInterrupt):
        input("\nPress Enter to return to the main menu.")


if __name__ == "__main__":
    main()
