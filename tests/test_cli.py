from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import game_grabber
from webgame_crawler.models import (
    CaptureResult,
    DownloadResult,
    DownloadSummary,
    FrameSignal,
    FrameSnapshot,
    ResourceRecord,
)


class _GBKLikeStream:
    encoding = "gbk"

    def __init__(self):
        self.values = []

    def write(self, value):
        value.encode(self.encoding)
        self.values.append(value)

    def flush(self):
        pass


class CliTests(unittest.TestCase):
    def _capture(self):
        frame = FrameSnapshot(
            url="https://game.example/index.html",
            canvas_count=1,
            engine="unity",
        )
        signal = FrameSignal(frame=frame, score=250)
        resources = [
            ResourceRecord(
                url="https://cdn.example/game.data.br?token=1",
                resource_type="fetch",
                frame_url=frame.url,
                status=200,
                encoded_size=10,
                response_headers={"x-amz-meta-uncompressed-length": "20"},
            ),
            ResourceRecord(
                url="https://cdn.example/game.wasm.br?token=2",
                resource_type="fetch",
                frame_url=frame.url,
                status=200,
                encoded_size=8,
            ),
        ]
        return CaptureResult(
            requested_url="https://portal.example/game",
            final_url="https://portal.example/game",
            title="Fixture: Game",
            frames=[frame],
            resources=resources,
            selected_frames=[signal],
            selected_resources=resources,
            cookies=[],
            user_agent="Fixture UA",
        )

    def test_run_writes_audit_report_and_returns_incomplete_exit_code(self):
        capture = self._capture()

        def capture_func(*_args, **_kwargs):
            return capture

        def download_func(resources, _cookies, output_dir, _main_host, **_kwargs):
            first_path = output_dir / "game.data.br"
            first_path.parent.mkdir(parents=True, exist_ok=True)
            first_path.write_bytes(b"0123456789")
            resources[0].local_path = "game.data.br"
            return DownloadSummary(
                results=[
                    DownloadResult(
                        url=resources[0].url,
                        ok=True,
                        bytes_written=10,
                        local_path=first_path,
                        status=200,
                    ),
                    DownloadResult(
                        url=resources[1].url,
                        ok=False,
                        status=403,
                        error="HTTP 403",
                    ),
                ]
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code = game_grabber.run(
                capture.requested_url,
                output_root=Path(temp_dir),
                capture_func=capture_func,
                download_func=download_func,
                printer=lambda *_: None,
            )
            report_path = Path(temp_dir) / "Fixture_ Game" / "_crawl" / "summary.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["captured"], 2)
        self.assertEqual(report["included"], 2)
        self.assertEqual(report["downloaded"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["encodedBytes"], 10)
        self.assertEqual(report["knownDecodedBytes"], 20)

    def test_safe_print_falls_back_when_console_cannot_encode_unicode(self):
        stream = _GBKLikeStream()

        game_grabber.safe_print("✅ complete", stream=stream)

        self.assertEqual(stream.values, ["? complete\n"])


if __name__ == "__main__":
    unittest.main()
