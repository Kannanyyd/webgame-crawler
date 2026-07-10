import unittest

from webgame_crawler.discovery import (
    build_frame_signals,
    is_tracking_url,
    select_game_frames,
    select_game_resources,
)
from webgame_crawler.models import FrameSnapshot, ResourceRecord


class DiscoveryTests(unittest.TestCase):
    def test_tracking_host_is_checked_without_trusting_query_text(self):
        ad_url = (
            "https://cm.g.doubleclick.net/partnerpixels?"
            "url=https%3A%2F%2Fgames.example.com%2Findex.html"
        )
        game_url = (
            "https://games.example.com/index.html?"
            "redirect=https%3A%2F%2Fcm.g.doubleclick.net%2Fpixel"
        )

        self.assertTrue(is_tracking_url(ad_url))
        self.assertFalse(is_tracking_url(game_url))

    def test_canvas_frame_with_large_binary_traffic_beats_ad_frame(self):
        ad_url = (
            "https://cm.g.doubleclick.net/partnerpixels?"
            "url=https%3A%2F%2Fgames.example.com%2Findex.html"
        )
        game_url = "https://play.example-cdn.net/build/index.html?version=7"
        frames = [
            FrameSnapshot(url=ad_url, parent_url="https://portal.example"),
            FrameSnapshot(
                url=game_url,
                parent_url="https://portal.example",
                canvas_count=1,
                engine="unity",
            ),
        ]
        resources = [
            ResourceRecord(
                url="https://assets.other-cdn.net/build/game.data.br?token=a",
                resource_type="fetch",
                frame_url=game_url,
                frame_ancestors=("https://portal.example",),
                status=200,
                encoded_size=21_000_000,
            ),
            ResourceRecord(
                url="https://cm.g.doubleclick.net/pixel?id=1",
                resource_type="image",
                frame_url=ad_url,
                status=200,
                encoded_size=43,
            ),
        ]

        signals = build_frame_signals(frames, resources)
        selected = select_game_frames(signals)

        self.assertEqual([signal.frame.url for signal in selected], [game_url])

    def test_selected_frame_keeps_cross_domain_assets_and_query_variants(self):
        game_url = "https://game.example/index.html"
        resources = [
            ResourceRecord(
                url="https://cdn.vendor.net/assets/data.bin?part=1",
                resource_type="fetch",
                frame_url=game_url,
                status=200,
            ),
            ResourceRecord(
                url="https://cdn.vendor.net/assets/data.bin?part=2",
                resource_type="fetch",
                frame_url=game_url,
                status=206,
            ),
            ResourceRecord(
                url="https://analytics.vendor.net/collect?game=1",
                resource_type="fetch",
                frame_url=game_url,
                status=200,
            ),
        ]

        selected = select_game_resources(resources, {game_url})

        self.assertEqual(
            [resource.url for resource in selected],
            [
                "https://cdn.vendor.net/assets/data.bin?part=1",
                "https://cdn.vendor.net/assets/data.bin?part=2",
            ],
        )


if __name__ == "__main__":
    unittest.main()
