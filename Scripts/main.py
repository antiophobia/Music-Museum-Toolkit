"""User-facing menu for Music Museum Toolkit."""

from archive import main as archive_main
from restore_playlist import main as restore_main


MENU = """\
Music Museum Toolkit

[1] Preserve Spotify playlist to Collection
[2] Restore Spotify playlist from Collection
[3] Exit
"""


def main():
    """Display the application menu until the user chooses to exit."""
    while True:
        print(MENU)
        try:
            selection = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting Music Museum Toolkit.")
            return

        if selection == "1":
            try:
                archive_main()
            except KeyboardInterrupt:
                print("\nPreservation interrupted. Returning to the main menu.")
            print()
        elif selection == "2":
            try:
                restore_main()
            except KeyboardInterrupt:
                print("\nRestoration paused. Returning to the main menu.")
            print()
        elif selection == "3":
            print("\nGoodbye.")
            return
        else:
            print("\nInvalid selection. Please choose 1, 2, or 3.\n")


if __name__ == "__main__":
    main()
