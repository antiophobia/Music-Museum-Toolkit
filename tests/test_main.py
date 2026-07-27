"""Offline tests for the Music Museum Toolkit application menu."""

import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import main as application


class ApplicationMenuTests(unittest.TestCase):
    def run_menu(self, selections):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=selections),
            patch("main.archive_main") as archive_main,
            redirect_stdout(output),
        ):
            application.main()
        return output.getvalue(), archive_main

    def test_preserve_invokes_archive_once_then_returns_to_menu(self):
        output, archive_main = self.run_menu(["1", "3"])
        archive_main.assert_called_once_with()
        self.assertGreaterEqual(output.count("[1] Preserve Spotify playlist"), 2)

    def test_restore_placeholder_returns_to_menu(self):
        output, archive_main = self.run_menu(["2", "3"])
        archive_main.assert_not_called()
        self.assertIn("Playlist restoration is coming next", output)
        self.assertGreaterEqual(output.count("[2] Restore Spotify playlist"), 2)

    def test_invalid_selection_is_handled(self):
        output, archive_main = self.run_menu(["invalid", "3"])
        archive_main.assert_not_called()
        self.assertIn("Invalid selection. Please choose 1, 2, or 3.", output)

    def test_ctrl_c_exits_cleanly(self):
        output, archive_main = self.run_menu([KeyboardInterrupt()])
        archive_main.assert_not_called()
        self.assertIn("Exiting Music Museum Toolkit.", output)

    def test_ctrl_c_from_archive_returns_to_menu(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=["1", "3"]),
            patch("main.archive_main", side_effect=KeyboardInterrupt),
            redirect_stdout(output),
        ):
            application.main()
        self.assertIn(
            "Preservation interrupted. Returning to the main menu.",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
