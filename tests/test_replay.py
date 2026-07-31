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
    def test_new_static_request_in_nested_frame_is_required_via_selected_ancestor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            har_path = Path(temp_dir) / "capture.har.zip"
            fixture = GameFixture()
            with fixture:
                capture = capture_game(
                    fixture.nested_game_url,
                    browser_path=BROWSER_PATH,
                    headless=True,
                    initial_wait_ms=250,
                    idle_seconds=0.5,
                    timeout_seconds=5,
                    har_path=har_path,
                )

            result = verify_replay(
                har_path,
                capture,
                browser_path=BROWSER_PATH,
            )

        selected_frame_urls = {
            signal.frame.url for signal in capture.selected_frames
        }
        runtime_failures = [
            failure for failure in result.failures if "/runtime.js?nonce=" in failure.url
        ]
        self.assertIn(fixture.nested_game_url, selected_frame_urls)
        self.assertNotIn(fixture.nested_child_url, selected_frame_urls)
        self.assertEqual(len(runtime_failures), 1)
        self.assertTrue(runtime_failures[0].required)
        self.assertEqual(runtime_failures[0].frame_url, fixture.nested_child_url)
        self.assertIn(fixture.nested_game_url, runtime_failures[0].frame_ancestors)
        self.assertFalse(result.complete)

    def test_har_http_replays_without_live_tcp_or_webrtc_udp_connections(self):
        with tempfile.TemporaryDirectory() as temp_dir, GameFixture() as fixture:
            har_path = Path(temp_dir) / "capture.har.zip"
            capture = capture_game(
                fixture.network_probe_url,
                browser_path=BROWSER_PATH,
                headless=True,
                initial_wait_ms=1_000,
                idle_seconds=0.5,
                timeout_seconds=5,
                har_path=har_path,
            )
            capture_tcp_connections = fixture.live_tcp_connections
            capture_udp_datagrams = fixture.live_udp_datagrams
            fixture.reset_live_network_counts()

            result = verify_replay(
                har_path,
                capture,
                browser_path=BROWSER_PATH,
            )
            replay_tcp_connections = fixture.live_tcp_connections
            replay_udp_datagrams = fixture.live_udp_datagrams

        self.assertGreaterEqual(capture_tcp_connections, 2)
        self.assertGreater(capture_udp_datagrams, 0)
        self.assertTrue(result.complete)
        self.assertIsNone(result.error)
        self.assertEqual(replay_tcp_connections, 0)
        self.assertEqual(replay_udp_datagrams, 0)

    def test_missing_required_request_delayed_after_existing_canvas_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            har_path = Path(temp_dir) / "capture.har.zip"
            fixture = GameFixture()
            with fixture:
                capture = capture_game(
                    fixture.auto_delayed_url,
                    browser_path=BROWSER_PATH,
                    headless=True,
                    har_path=har_path,
                )
            incomplete_har_path = Path(temp_dir) / "incomplete.har.zip"
            _remove_har_entry(
                har_path,
                incomplete_har_path,
                fixture.late_asset_url,
            )

            result = verify_replay(
                incomplete_har_path,
                capture,
                browser_path=BROWSER_PATH,
            )

        self.assertIn(fixture.late_asset_url, [item.url for item in result.failures])
        self.assertEqual(result.required_failed, 1)
        self.assertFalse(result.complete)

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
        self.assertTrue(result.complete, result.error)
        self.assertIsNone(result.error)

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
