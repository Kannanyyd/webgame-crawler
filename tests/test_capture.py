import unittest
from pathlib import Path

from tests.fixtures.game_site import GameFixture
from webgame_crawler.capture import capture_game


class CaptureTests(unittest.TestCase):
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

        self.assertEqual(selected_urls, [fixture.game_url])
        self.assertIn(fixture.asset_url, resource_urls)
        self.assertNotIn("/ad?", selected_urls[0])


if __name__ == "__main__":
    unittest.main()
