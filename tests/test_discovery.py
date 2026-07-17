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

    def test_generic_adtech_hosts_are_tracking_without_portal_rules(self):
        urls = [
            "https://fafvertizing.example/prebid.js",
            "https://ats-wrapper.privacymanager.io/ats.js",
            "https://invstatic.creativecdn.com/encrypted.js",
            "https://tags.crwdcntrl.net/pixel.js",
            "https://oa.openxcdn.net/esp.js",
        ]

        self.assertTrue(all(is_tracking_url(url) for url in urls))

    def test_google_ad_quality_and_consent_hosts_are_tracking(self):
        self.assertTrue(is_tracking_url("https://ep1.adtrafficquality.google/ping"))
        self.assertTrue(
            is_tracking_url("https://fundingchoicesmessages.google.com/init")
        )
        self.assertFalse(is_tracking_url("https://fonts.gstatic.com/font.woff2"))

    def test_pixel_themed_game_paths_are_not_tracking(self):
        self.assertFalse(
            is_tracking_url(
                "https://cdn.example/games/pixel-adventure/index.html"
            )
        )
        self.assertFalse(
            is_tracking_url("https://cdn.example/sprites/pixel.png")
        )

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

    def test_blob_runtime_resources_are_not_selected_for_http_download(self):
        game_url = "https://game.example/index.html"
        resources = [
            ResourceRecord(
                url="blob:https://game.example/runtime-worker",
                resource_type="script",
                frame_url=game_url,
                status=200,
            )
        ]

        selected = select_game_resources(resources, {game_url})

        self.assertEqual(selected, [])

    def test_portal_without_canvas_or_engine_is_not_a_game_context(self):
        portal = FrameSnapshot(url="https://portal.example/game")
        resources = [
            ResourceRecord(
                url="https://portal.example/app.js",
                resource_type="script",
                frame_url=portal.url,
                status=200,
                encoded_size=20_000_000,
            )
        ]

        selected = select_game_frames(build_frame_signals([portal], resources))

        self.assertEqual(selected, [])

    def test_resource_rich_dom_game_subframe_is_selected_without_canvas(self):
        portal_url = "https://portal.example/games/pipe-puzzle"
        game_url = "https://app-123.games-cdn.example/release/index.html"
        tag_manager_url = (
            "https://static.example/pixels/google-tag-manager.html"
        )
        frames = [
            FrameSnapshot(url=portal_url),
            FrameSnapshot(url=game_url, parent_url=portal_url),
            FrameSnapshot(url=tag_manager_url, parent_url=portal_url),
        ]
        resources = [
            ResourceRecord(
                url=f"https://app-123.games-cdn.example/release/assets/{index}.js",
                resource_type="script",
                frame_url=game_url,
                status=200,
                encoded_size=16_384,
            )
            for index in range(5)
        ]
        resources.extend(
            ResourceRecord(
                url=f"https://static.example/pixels/tracker-{index}.js",
                resource_type="script",
                frame_url=tag_manager_url,
                status=200,
                encoded_size=100_000,
            )
            for index in range(6)
        )

        selected = select_game_frames(build_frame_signals(frames, resources))

        self.assertEqual([signal.frame.url for signal in selected], [game_url])

    def test_dom_frame_does_not_use_non_game_bytes_to_meet_threshold(self):
        portal_url = "https://portal.example/game"
        widget_url = "https://widgets.example/frame.html"
        frames = [
            FrameSnapshot(url=portal_url),
            FrameSnapshot(url=widget_url, parent_url=portal_url),
        ]
        resources = [
            ResourceRecord(
                url=f"https://widgets.example/script-{index}.js",
                resource_type="script",
                frame_url=widget_url,
                status=200,
                encoded_size=1_024,
            )
            for index in range(4)
        ]
        resources.append(
            ResourceRecord(
                url="https://widgets.example/large-response",
                method="POST",
                resource_type="xhr",
                frame_url=widget_url,
                status=200,
                encoded_size=1_000_000,
            )
        )

        selected = select_game_frames(build_frame_signals(frames, resources))

        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
