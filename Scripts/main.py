"""User-facing menu with offline-first, lazy feature loading."""

import sys

from app_runtime import (
    APP_VERSION, PROJECT_ROOT, display_path, initialize_runtime_directories,
    write_error_log,
)


# Running ``python Scripts\main.py`` makes Scripts the first import location.
# Add the root derived from this installation so the Config package remains
# available regardless of the Windows working directory or installation path.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


MENU = """\
====================================================
Music Museum Toolkit
{APP_VERSION}
====================================================

[1] Preserve Spotify playlist to Collection
[2] Restore Spotify playlist from Collection
[3] Museum
[4] Exit
""".format(APP_VERSION=APP_VERSION)


def _load_preservation_handler():
    from archive import main as archive_main
    return archive_main


def _load_restoration_handler():
    from restore_playlist import main as restore_main
    return restore_main


def _load_museum_handler():
    from museum import main as museum_main
    return museum_main


def _missing_spotify_configuration():
    from Config.config import missing_spotify_configuration
    return missing_spotify_configuration()


def _show_spotify_setup(feature):
    print("\n" + "-" * 60)
    print("SPOTIFY API SETUP REQUIRED\n")
    print(f"{feature} connects directly to Spotify and requires")
    print("Spotify Developer credentials.\n")
    print("Museum browsing and Spotify-data imports do NOT require this setup.\n")
    print("Configuration file:")
    print("    .env\n")
    print("Template:")
    print("    .env.example\n")
    print("[1] Show setup instructions")
    print("[2] Return to main menu")
    print("-" * 60)
    while True:
        try:
            choice = input("\nSelect an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to the main menu.")
            return
        if choice == "1":
            print("\nSPOTIFY DEVELOPER SETUP\n")
            print("1. Create a Spotify Developer application.")
            print("2. Copy .env.example to a new file named .env.")
            print("3. Put your client ID and client secret in .env.")
            print("4. Keep .env private; never commit or share it.")
            print("5. Return here and choose Preserve or Restore again.\n")
            try:
                input("Press Enter to return to the main menu.")
            except (EOFError, KeyboardInterrupt):
                pass
            return
        if choice in {"", "2"}:
            return
        print("\nInvalid selection. Please choose 1 or 2.")


def _report_unexpected(context, error, project_root):
    print("\nMusic Museum Toolkit encountered an unexpected error.")
    try:
        path = write_error_log(context, error, project_root)
    except OSError:
        print("A diagnostic log could not be written.")
    else:
        print("\nDetails were written to:")
        print(f"    {display_path(path, project_root)}")
    print(f"\nShort summary: {type(error).__name__}")
    print("Returning to the main menu.")


def _run_feature(context, loader, project_root, interrupted_message):
    try:
        handler = loader()
        handler()
    except KeyboardInterrupt:
        print(f"\n{interrupted_message}")
    except Exception as error:
        _report_unexpected(context, error, project_root)


def main(project_root=None):
    """Display the application menu until the user chooses to exit."""
    runtime_root = project_root or PROJECT_ROOT
    try:
        initialize_runtime_directories(runtime_root)
    except OSError as error:
        print("Music Museum Toolkit could not prepare its local data folders.")
        print(f"Short summary: {type(error).__name__}")
        return 1
    while True:
        print(MENU)
        try:
            selection = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting Music Museum Toolkit.")
            return

        if selection == "1":
            try:
                missing = _missing_spotify_configuration()
            except Exception as error:
                _report_unexpected("Spotify configuration", error, runtime_root)
            else:
                if missing:
                    _show_spotify_setup("Preserve")
                else:
                    _run_feature(
                        "Preserve", _load_preservation_handler, runtime_root,
                        "Preservation interrupted. Returning to the main menu.",
                    )
            print()
        elif selection == "2":
            try:
                missing = _missing_spotify_configuration()
            except Exception as error:
                _report_unexpected("Spotify configuration", error, runtime_root)
            else:
                if missing:
                    _show_spotify_setup("Restore")
                else:
                    _run_feature(
                        "Restore", _load_restoration_handler, runtime_root,
                        "Restoration paused. Returning to the main menu.",
                    )
            print()
        elif selection == "3":
            _run_feature(
                "Museum", _load_museum_handler, runtime_root,
                "Museum closed. Returning to the main menu.",
            )
            print()
        elif selection == "4":
            print("\nGoodbye.")
            return 0
        else:
            print("\nInvalid selection. Please choose 1, 2, 3, or 4.\n")


if __name__ == "__main__":
    raise SystemExit(main())
