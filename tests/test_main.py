"""Offline tests for the Music Museum Toolkit application menu."""

import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import pandas as pd


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import main as application
import museum
from _test_support import synthetic_workspace


class ApplicationMenuTests(unittest.TestCase):
    def run_menu(self, selections, missing=None):
        output = StringIO()
        archive_main = Mock(); restore_main = Mock(); museum_main = Mock()
        with synthetic_workspace() as runtime_root:
            with (
                patch("builtins.input", side_effect=selections),
                patch("main._missing_spotify_configuration", return_value=missing or []),
                patch("main._load_preservation_handler", return_value=archive_main),
                patch("main._load_restoration_handler", return_value=restore_main),
                patch("main._load_museum_handler", return_value=museum_main),
                redirect_stdout(output),
            ):
                application.main(runtime_root)
        return output.getvalue(), archive_main, restore_main, museum_main

    def test_preserve_invokes_archive_once_then_returns_to_menu(self):
        output, archive_main, restore_main, _ = self.run_menu(["1", "4"])
        archive_main.assert_called_once_with()
        restore_main.assert_not_called()
        self.assertGreaterEqual(output.count("[1] Preserve Spotify playlist"), 2)

    def test_restore_dispatches_once_then_returns_to_menu(self):
        output, archive_main, restore_main, _ = self.run_menu(["2", "4"])
        archive_main.assert_not_called()
        restore_main.assert_called_once_with()
        self.assertGreaterEqual(output.count("[2] Restore Spotify playlist"), 2)

    def test_invalid_selection_is_handled(self):
        output, archive_main, restore_main, _ = self.run_menu(["invalid", "4"])
        archive_main.assert_not_called()
        restore_main.assert_not_called()
        self.assertIn("Invalid selection. Please choose 1, 2, 3, or 4.", output)

    def test_ctrl_c_exits_cleanly(self):
        output, archive_main, restore_main, _ = self.run_menu([KeyboardInterrupt()])
        archive_main.assert_not_called()
        restore_main.assert_not_called()
        self.assertIn("Exiting Music Museum Toolkit.", output)

    def test_ctrl_c_from_archive_returns_to_menu(self):
        output = StringIO()
        interrupted = Mock(side_effect=KeyboardInterrupt)
        with (
            patch("builtins.input", side_effect=["1", "4"]),
            patch("main._missing_spotify_configuration", return_value=[]),
            patch("main._load_preservation_handler", return_value=interrupted),
            patch("main.initialize_runtime_directories"),
            redirect_stdout(output),
        ):
            application.main()
        self.assertIn(
            "Preservation interrupted. Returning to the main menu.",
            output.getvalue(),
        )

    def test_museum_dispatches_once_then_returns_to_menu(self):
        _, archive_main, restore_main, museum_main = self.run_menu(["3", "4"])
        archive_main.assert_not_called()
        restore_main.assert_not_called()
        museum_main.assert_called_once_with()

    def test_preserve_without_credentials_explains_setup_and_returns(self):
        output, archive_main, _, _ = self.run_menu(
            ["1", "2", "4"],
            ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"],
        )
        archive_main.assert_not_called()
        self.assertIn("SPOTIFY API SETUP REQUIRED", output)
        self.assertIn("Museum browsing and Spotify-data imports do NOT require", output)
        self.assertNotIn("Traceback", output)

    def test_restore_without_credentials_explains_setup_and_returns(self):
        output, _, restore_main, _ = self.run_menu(
            ["2", "2", "4"],
            ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"],
        )
        restore_main.assert_not_called()
        self.assertIn("SPOTIFY API SETUP REQUIRED", output)
        self.assertIn("Configuration file:", output)
        self.assertNotIn("Traceback", output)

    def test_no_credentials_can_open_empty_museum_and_reach_zip_discovery(self):
        output = StringIO()
        with synthetic_workspace() as runtime_root:
            with (
                patch.dict(os.environ, {
                    "SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": "",
                }),
                patch("museum.load_existing_collection", return_value=pd.DataFrame()),
                patch("museum.load_events", return_value=[]),
                patch("museum.load_exhibits", return_value=[]),
                patch("museum.load_manifest", return_value=pd.DataFrame()),
                patch("museum.discover_default_archives", return_value=[]),
                patch("main._load_museum_handler", return_value=museum.main),
                patch("builtins.input", side_effect=[
                    "3", "1", "7", "", "8", "4",
                ]),
                redirect_stdout(output),
            ):
                application.main(runtime_root)
            for relative in (
                "Input", os.path.join("Input", "Spotify Data"), "Output", "Logs"
            ):
                self.assertTrue(os.path.isdir(os.path.join(runtime_root, relative)))
        visible = output.getvalue()
        self.assertIn("Music Museum Toolkit", visible)
        self.assertIn("Your Museum has not been built yet.", visible)
        self.assertIn("MUSEUM DATA IMPORT", visible)
        self.assertIn("No Spotify ZIP archives were found.", visible)
        self.assertNotIn("Traceback", visible)

    def test_unexpected_feature_error_is_logged_and_menu_survives(self):
        output = StringIO()
        failed = Mock(side_effect=RuntimeError("synthetic failure"))
        with synthetic_workspace() as runtime_root:
            with (
                patch("main._missing_spotify_configuration", return_value=[]),
                patch("main._load_preservation_handler", return_value=failed),
                patch("builtins.input", side_effect=["1", "4"]),
                redirect_stdout(output),
            ):
                application.main(runtime_root)
            self.assertEqual(len(os.listdir(os.path.join(runtime_root, "Logs"))), 1)
        self.assertIn("encountered an unexpected error", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
