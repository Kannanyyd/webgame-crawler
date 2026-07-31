import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import zipfile

from tests.fixtures.game_site import GameFixture
from webgame_crawler.har import inspect_har
from webgame_crawler.capture import (
    _NetworkActivity,
    _should_detect_engine,
    capture_game,
    navigate_page,
)


class CaptureTests(unittest.TestCase):
    def test_capture_writes_full_har_with_attached_bodies(self):
        browser_path = Path(__file__).resolve().parents[1] / ".pw-browsers"
        with tempfile.TemporaryDirectory() as temp_dir, GameFixture() as fixture:
            har_path = Path(temp_dir) / "capture.har.zip"
            capture_game(
                fixture.url,
                browser_path=browser_path,
                headless=True,
                initial_wait_ms=250,
                idle_seconds=0.5,
                timeout_seconds=8,
                har_path=har_path,
            )
            archive = inspect_har(har_path)
            with zipfile.ZipFile(har_path) as har_archive:
                member_names = har_archive.namelist()
                har_member = next(
                    name for name in member_names if name.endswith(".har")
                )
                har = json.loads(har_archive.read(har_member))
                asset_entry = next(
                    entry
                    for entry in har["log"]["entries"]
                    if entry["request"]["url"] == fixture.asset_url
                )
                attachment = asset_entry["response"]["content"]["_file"]
                attachment_body = har_archive.read(attachment)
                response_headers = {
                    header["name"].lower(): header["value"]
                    for header in asset_entry["response"]["headers"]
                }

        self.assertTrue(archive.valid, archive.error)
        self.assertGreater(archive.entry_count, 0)
        self.assertGreater(archive.body_count, 0)
        self.assertIn(attachment, member_names)
        self.assertEqual(attachment_body, b"fixture-game-binary")
        self.assertEqual(asset_entry["response"]["status"], 200)
        self.assertEqual(
            asset_entry["response"]["content"]["mimeType"],
            "application/octet-stream",
        )
        self.assertEqual(response_headers["content-type"], "application/octet-stream")
        self.assertEqual(response_headers["access-control-allow-origin"], "*")
        self.assertEqual(
            response_headers["content-length"],
            str(len(b"fixture-game-binary")),
        )
        self.assertIn("timings", asset_entry)

    def test_engine_detection_skips_blank_and_low_traffic_frames(self):
        self.assertFalse(_should_detect_engine("about:blank", 0, 0, 0))
        self.assertFalse(
            _should_detect_engine("https://ads.example/frame", 0, 2, 512)
        )
        self.assertTrue(
            _should_detect_engine("https://game.example/index.html", 1, 0, 0)
        )
        self.assertTrue(
            _should_detect_engine("https://game.example/index.html", 0, 5, 100_000)
        )

    def test_navigation_error_is_returned_for_partial_page_analysis(self):
        class FailingPage:
            def goto(self, *_args, **_kwargs):
                raise RuntimeError("navigation timed out")

        error = navigate_page(FailingPage(), "https://game.example")

        self.assertEqual(error, "navigation timed out")

    def test_network_idle_ignores_extensionless_api_polling(self):
        activity = _NetworkActivity()
        api_poll = SimpleNamespace(
            method="GET",
            url="https://api.example.com/realtime",
            resource_type="xhr",
        )
        game_asset = SimpleNamespace(
            method="GET",
            url="https://cdn.example.com/Build/game.data.br?token=1",
            resource_type="fetch",
        )

        activity.started(api_poll)
        activity.started(game_asset)

        self.assertNotIn(id(api_poll), activity.inflight)
        self.assertIn(id(game_asset), activity.inflight)

    def test_network_idle_focuses_on_canvas_frame(self):
        activity = _NetworkActivity()
        portal_request = SimpleNamespace(
            method="GET",
            url="https://portal.example/app.js",
            resource_type="script",
            frame=SimpleNamespace(url="https://portal.example/game"),
        )
        game_request = SimpleNamespace(
            method="GET",
            url="https://cdn.example/game.data.br",
            resource_type="fetch",
            frame=SimpleNamespace(url="https://game.example/index.html"),
        )
        activity.started(portal_request)
        activity.started(game_request)

        activity.focus_frames({"https://game.example/index.html"})

        self.assertNotIn(id(portal_request), activity.inflight)
        self.assertIn(id(game_request), activity.inflight)

    def test_selects_canvas_frame_and_keeps_cross_origin_asset(self):
        browser_path = Path(__file__).resolve().parents[1] / ".pw-browsers"
        with GameFixture() as fixture:
            result = capture_game(
                fixture.url,
                browser_path=browser_path,
                headless=True,
                initial_wait_ms=250,
                idle_seconds=0.5,
                timeout_seconds=8,
            )

        selected_urls = [signal.frame.url for signal in result.selected_frames]
        resource_urls = [resource.url for resource in result.selected_resources]
        all_urls = [resource.url for resource in result.resources]

        self.assertEqual(selected_urls, [fixture.game_url])
        self.assertIn(fixture.asset_url, resource_urls)
        self.assertIn(fixture.late_asset_url, resource_urls)
        self.assertNotIn("/ad?", selected_urls[0])
        self.assertFalse(any(url.endswith("/video-player") for url in all_urls))

    def test_retries_start_control_until_delayed_button_appears(self):
        browser_path = Path(__file__).resolve().parents[1] / ".pw-browsers"
        with GameFixture() as fixture:
            result = capture_game(
                fixture.delayed_url,
                browser_path=browser_path,
                headless=True,
                initial_wait_ms=0,
                idle_seconds=0.25,
                timeout_seconds=6,
            )

        self.assertEqual(
            [signal.frame.url for signal in result.selected_frames],
            [fixture.game_url],
        )


if __name__ == "__main__":
    unittest.main()
