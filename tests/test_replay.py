import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tests.fixtures.game_site import GameFixture
from webgame_crawler.capture import capture_game
from webgame_crawler.replay import verify_replay


BROWSER_PATH = Path(__file__).resolve().parents[1] / ".pw-browsers"


def _capture_fixture(har_path: Path):
    fixture = GameFixture()
    with fixture:
        capture = capture_game(
            fixture.url,
            browser_path=BROWSER_PATH,
            headless=True,
            initial_wait_ms=250,
            idle_seconds=0.5,
            timeout_seconds=8,
            har_path=har_path,
        )
    return fixture, capture


def _remove_har_entry(source: Path, destination: Path, request_url: str) -> None:
    removed = 0
    with zipfile.ZipFile(source) as source_archive, zipfile.ZipFile(
        destination, "w"
    ) as destination_archive:
        for member in source_archive.infolist():
            contents = source_archive.read(member)
            if member.filename == "har.har":
                har = json.loads(contents)
                entries = har["log"]["entries"]
                retained = []
                for entry in entries:
                    if entry["request"]["url"] == request_url:
                        removed += 1
                    else:
                        retained.append(entry)
                har["log"]["entries"] = retained
                contents = json.dumps(har).encode("utf-8")
            destination_archive.writestr(member, contents)
    if removed != 1:
        raise AssertionError(f"expected one HAR entry for {request_url}, removed {removed}")


class ReplayTests(unittest.TestCase):
    def test_complete_har_reaches_the_game_without_required_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            har_path = Path(temp_dir) / "capture.har.zip"
            _, capture = _capture_fixture(har_path)

            result = verify_replay(
                har_path,
                capture,
                browser_path=BROWSER_PATH,
                timeout_seconds=8,
            )

        self.assertTrue(result.archive.valid, result.archive.error)
        self.assertTrue(result.reached_game_surface)
        self.assertEqual(result.required_failed, 0)

    def test_replay_reports_removed_game_asset_as_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            har_path = Path(temp_dir) / "capture.har.zip"
            fixture, capture = _capture_fixture(har_path)
            incomplete_har_path = Path(temp_dir) / "incomplete.har.zip"
            _remove_har_entry(har_path, incomplete_har_path, fixture.asset_url)

            result = verify_replay(
                incomplete_har_path,
                capture,
                browser_path=BROWSER_PATH,
                timeout_seconds=8,
            )

        self.assertIn(fixture.asset_url, [item.url for item in result.failures])
        self.assertEqual(result.required_failed, 1)
        self.assertFalse(result.complete)

    def test_replay_reports_changing_portal_telemetry_as_optional(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            har_path = Path(temp_dir) / "capture.har.zip"
            _, capture = _capture_fixture(har_path)

            result = verify_replay(
                har_path,
                capture,
                browser_path=BROWSER_PATH,
                timeout_seconds=8,
            )

        telemetry = [
            item for item in result.failures if "/analytics?nonce=" in item.url
        ]
        self.assertEqual(len(telemetry), 1)
        self.assertFalse(telemetry[0].required)


if __name__ == "__main__":
    unittest.main()
