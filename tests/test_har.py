import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from webgame_crawler.har import inspect_har


def _write_har_zip(path: Path, include_attachment: bool = True) -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {"url": "https://game.example/asset.bin"},
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/octet-stream",
                            "size": 4,
                            "_file": "resources/body.bin",
                        },
                    },
                }
            ]
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("har.har", json.dumps(har))
        if include_attachment:
            archive.writestr("resources/body.bin", b"body")


class HarInspectionTests(unittest.TestCase):
    def test_inspect_har_counts_entries_and_attached_response_bodies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.har.zip"
            _write_har_zip(path)
            expected_size = path.stat().st_size

            result = inspect_har(path)

        self.assertTrue(result.valid)
        self.assertEqual(result.size, expected_size)
        self.assertEqual(result.entry_count, 1)
        self.assertEqual(result.body_count, 1)
        self.assertIsNone(result.error)

    def test_inspect_har_rejects_a_missing_body_attachment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.har.zip"
            _write_har_zip(path, include_attachment=False)

            result = inspect_har(path)

        self.assertFalse(result.valid)
        self.assertIn("resources/body.bin", result.error)

    def test_inspect_har_rejects_invalid_har_encoding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.har.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("har.har", b"\x80")

            result = inspect_har(path)

        self.assertFalse(result.valid)
        self.assertIsNotNone(result.error)

    def test_inspect_har_rejects_duplicate_har_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.har.zip"
            _write_har_zip(path)
            with zipfile.ZipFile(path, "a") as archive:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr("har.har", archive.read("har.har"))

            result = inspect_har(path)

        self.assertFalse(result.valid)
        self.assertIn("exactly one .har member", result.error)


if __name__ == "__main__":
    unittest.main()
