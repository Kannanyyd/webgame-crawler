import unittest

from tests.live_smoke import summarize_capture, validate_capture
from webgame_crawler.models import (
    CaptureResult,
    FrameSignal,
    FrameSnapshot,
    ResourceRecord,
)


class LiveSmokeTests(unittest.TestCase):
    def test_summary_reports_selected_engine_and_core_bytes(self):
        frame = FrameSnapshot(
            url="https://game.example/index.html",
            canvas_count=1,
            engine="unity",
        )
        resources = [
            ResourceRecord(
                url="https://cdn.example/game.data.br",
                frame_url=frame.url,
                status=200,
                encoded_size=10,
            ),
            ResourceRecord(
                url="https://cdn.example/game.wasm.br",
                frame_url=frame.url,
                status=200,
                encoded_size=8,
            ),
        ]
        capture = CaptureResult(
            requested_url="https://portal.example/game",
            final_url="https://portal.example/game",
            title="Game",
            frames=[frame],
            resources=resources,
            selected_frames=[FrameSignal(frame=frame, score=250, encoded_size=18)],
            selected_resources=resources,
        )

        summary = summarize_capture(capture)

        self.assertEqual(validate_capture(capture), [])
        self.assertEqual(summary["engines"], ["unity"])
        self.assertEqual(summary["selectedResources"], 2)
        self.assertEqual(summary["encodedBytes"], 18)


if __name__ == "__main__":
    unittest.main()
