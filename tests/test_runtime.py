"""Credential-free first-run, runtime-folder, logging, and BAT tests."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
sys.path.insert(0, ROOT)

import app_runtime
from Config import config
from _test_support import synthetic_workspace


class FirstRunRuntimeTests(unittest.TestCase):
    def test_required_directories_are_created_without_overwriting_data(self):
        with synthetic_workspace() as root:
            existing = Path(root) / "Input"
            existing.mkdir()
            marker = existing / "keep.txt"
            marker.write_text("keep me", encoding="utf-8")
            first = app_runtime.initialize_runtime_directories(root)
            second = app_runtime.initialize_runtime_directories(root)
            self.assertEqual(first, second)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")
            for relative in app_runtime.RUNTIME_DIRECTORIES:
                self.assertTrue((Path(root) / relative).is_dir())

    def test_configuration_is_importable_and_reports_missing_without_env(self):
        with synthetic_workspace() as root, patch.object(
            config, "ENV_FILE", Path(root) / ".env"
        ), patch.dict(os.environ, {
            "SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": "",
        }):
            missing = config.missing_spotify_configuration()
            with self.assertRaises(config.SpotifyConfigurationError):
                config.require_spotify_configuration()
        self.assertIn("SPOTIFY_CLIENT_ID", missing)
        self.assertIn("SPOTIFY_CLIENT_SECRET", missing)

    def test_error_log_redacts_secrets_and_absolute_root(self):
        with synthetic_workspace() as root, patch.dict(os.environ, {
            "SPOTIFY_CLIENT_SECRET": "do-not-log-this-secret",
        }):
            try:
                raise RuntimeError(
                    f"failure in {root}: do-not-log-this-secret"
                )
            except RuntimeError as error:
                path = app_runtime.write_error_log("synthetic", error, root)
            contents = path.read_text(encoding="utf-8")
            self.assertNotIn("do-not-log-this-secret", contents)
            self.assertNotIn(str(Path(root).resolve()), contents)
            self.assertIn("Exception type: RuntimeError", contents)
            redacted = app_runtime._redact(
                f"{root} do-not-log-this-secret", root
            )
            self.assertEqual(redacted, "<PROJECT_ROOT> <REDACTED>")

    def test_bat_changes_to_its_own_directory_before_python(self):
        contents = (Path(ROOT) / "Music Museum Toolkit.bat").read_text(
            encoding="utf-8"
        ).casefold()
        change = contents.index('cd /d "%~dp0"')
        launch = contents.index('python "scripts\\main.py"')
        self.assertLess(change, launch)
        self.assertNotIn("c:\\users\\admin", contents)


if __name__ == "__main__":
    unittest.main()
