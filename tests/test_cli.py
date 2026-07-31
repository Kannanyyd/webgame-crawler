from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import game_grabber
from webgame_crawler.models import (
    CaptureResult,
    DownloadResult,
    DownloadSummary,
    FrameSignal,
    FrameSnapshot,
    HarArchiveInfo,
    ReplayFailure,
    ReplaySummary,
    ResourceRecord,
)


def _write_valid_har_zip(path: Path) -> int:
    har = {
        "log": {
            "entries": [
                {
                    "request": {"url": "https://game.example/index.html"},
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "text/html",
                            "size": 4,
                            "text": "game",
                        },
                    },
                }
            ]
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("capture.har", json.dumps(har))
    return path.stat().st_size


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
        captured_har = {}

        def capture_func(*_args, har_path, **_kwargs):
            captured_har["size"] = _write_valid_har_zip(har_path)
            return capture

        def replay_func(har_path, replay_capture, **_kwargs):
            return ReplaySummary(
                archive=HarArchiveInfo(
                    har_path,
                    True,
                    size=har_path.stat().st_size,
                    entry_count=1,
                    body_count=1,
                ),
                requested_url=replay_capture.requested_url,
                final_url=replay_capture.final_url,
                reached_game_surface=True,
                failures=[
                    ReplayFailure(
                        url="https://cdn.example/game.wasm.br?token=2",
                        resource_type="fetch",
                        frame_url="https://game.example/index.html",
                        error="request not found in HAR",
                        required=True,
                    )
                ],
            )

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
                replay_func=replay_func,
                printer=lambda *_: None,
            )
            crawl_dir = Path(temp_dir) / "Fixture_ Game" / "_crawl"
            installed_har = crawl_dir / "capture.har.zip"
            report_path = crawl_dir / "summary.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            replay_report = json.loads(
                (crawl_dir / "replay-verification.json").read_text(encoding="utf-8")
            )
            installed_har_exists = installed_har.is_file()

        self.assertEqual(exit_code, 1)
        self.assertTrue(installed_har_exists)
        self.assertEqual(report["captured"], 2)
        self.assertEqual(report["included"], 2)
        self.assertEqual(report["downloaded"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["requiredFailed"], 1)
        self.assertEqual(report["encodedBytes"], 10)
        self.assertEqual(report["knownDecodedBytes"], 20)
        self.assertEqual(report["harBytes"], captured_har["size"])
        self.assertFalse(report["replayComplete"])
        self.assertEqual(report["replayFailed"], 1)
        self.assertEqual(report["replayRequiredFailed"], 1)
        self.assertEqual(replay_report["archive"], str(installed_har))
        self.assertTrue(replay_report["archiveValid"])
        self.assertFalse(replay_report["complete"])
        self.assertEqual(
            replay_report["failures"],
            [
                {
                    "url": "https://cdn.example/game.wasm.br?token=2",
                    "method": "GET",
                    "type": "fetch",
                    "frameUrl": "https://game.example/index.html",
                    "error": "request not found in HAR",
                    "required": True,
                }
            ],
        )

    def test_run_does_not_fail_when_only_optional_resource_is_missing(self):
        capture = self._capture()

        def capture_func(*_args, har_path, **_kwargs):
            _write_valid_har_zip(har_path)
            return capture

        def replay_func(har_path, replay_capture, **_kwargs):
            return ReplaySummary(
                archive=HarArchiveInfo(
                    har_path,
                    True,
                    size=har_path.stat().st_size,
                    entry_count=1,
                    body_count=1,
                ),
                requested_url=replay_capture.requested_url,
                final_url=replay_capture.final_url,
                reached_game_surface=True,
            )

        def download_func(resources, _cookies, output_dir, _main_host, **_kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            return DownloadSummary(
                results=[
                    DownloadResult(
                        url=resources[0].url,
                        ok=True,
                        bytes_written=10,
                        status=200,
                    ),
                    DownloadResult(
                        url="https://cdn.example/template.wasm",
                        ok=False,
                        status=404,
                        error="HTTP 404",
                        required=False,
                    ),
                ]
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code = game_grabber.run(
                capture.requested_url,
                output_root=Path(temp_dir),
                capture_func=capture_func,
                download_func=download_func,
                replay_func=replay_func,
                printer=lambda *_: None,
            )

        self.assertEqual(exit_code, 0)

    def test_run_reports_invalid_har_without_attempting_replay(self):
        capture = self._capture()

        def capture_func(*_args, har_path, **_kwargs):
            _write_valid_har_zip(har_path)
            return capture

        def download_func(*_args, **_kwargs):
            return DownloadSummary()

        def inspect_har_func(har_path):
            return HarArchiveInfo(
                har_path,
                False,
                size=har_path.stat().st_size,
                error="invalid fixture archive",
            )

        def replay_func(*_args, **_kwargs):
            raise AssertionError("invalid HAR must not be replayed")

        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code = game_grabber.run(
                capture.requested_url,
                output_root=Path(temp_dir),
                capture_func=capture_func,
                download_func=download_func,
                replay_func=replay_func,
                inspect_har_func=inspect_har_func,
                printer=lambda *_: None,
            )
            replay_report = json.loads(
                (
                    Path(temp_dir)
                    / "Fixture_ Game"
                    / "_crawl"
                    / "replay-verification.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 1)
        self.assertFalse(replay_report["archiveValid"])
        self.assertFalse(replay_report["complete"])
        self.assertEqual(replay_report["error"], "invalid fixture archive")

    def test_run_cleans_only_its_temporary_har_on_early_return(self):
        capture = self._capture()
        capture.selected_frames = []
        capture.selected_resources = []
        temporary_paths = []

        def capture_func(*_args, har_path, **_kwargs):
            temporary_paths.append(har_path)
            self.assertFalse(har_path.exists())
            _write_valid_har_zip(har_path)
            return capture

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            sentinel = output_root / "keep.har.zip"
            sentinel.write_bytes(b"keep")

            exit_code = game_grabber.run(
                capture.requested_url,
                output_root=output_root,
                capture_func=capture_func,
                printer=lambda *_: None,
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(len(temporary_paths), 1)
            self.assertFalse(temporary_paths[0].exists())
            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_run_cleans_only_its_temporary_har_when_capture_raises(self):
        temporary_paths = []

        def capture_func(*_args, har_path, **_kwargs):
            temporary_paths.append(har_path)
            self.assertFalse(har_path.exists())
            _write_valid_har_zip(har_path)
            raise RuntimeError("capture failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            sentinel = output_root / "keep.har.zip"
            sentinel.write_bytes(b"keep")

            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                game_grabber.run(
                    "https://portal.example/game",
                    output_root=output_root,
                    capture_func=capture_func,
                    printer=lambda *_: None,
                )

            self.assertEqual(len(temporary_paths), 1)
            self.assertFalse(temporary_paths[0].exists())
            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_run_reports_har_installation_failure_and_cleans_temporary_file(self):
        capture = self._capture()
        temporary_paths = []

        def capture_func(*_args, har_path, **_kwargs):
            temporary_paths.append(har_path)
            _write_valid_har_zip(har_path)
            return capture

        def download_func(*_args, **_kwargs):
            return DownloadSummary()

        def inspect_har_func(har_path):
            return HarArchiveInfo(har_path, False, error="install failed")

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            game_grabber, "install_har", side_effect=OSError("install failed")
        ):
            output_root = Path(temp_dir)
            sentinel = output_root / "keep.har.zip"
            sentinel.write_bytes(b"keep")

            exit_code = game_grabber.run(
                capture.requested_url,
                output_root=output_root,
                capture_func=capture_func,
                download_func=download_func,
                inspect_har_func=inspect_har_func,
                printer=lambda *_: None,
            )
            report = json.loads(
                (
                    output_root / "Fixture_ Game" / "_crawl" / "summary.json"
                ).read_text(encoding="utf-8")
            )

            self.assertEqual(exit_code, 1)
            self.assertFalse(report["replayComplete"])
            self.assertEqual(len(temporary_paths), 1)
            self.assertFalse(temporary_paths[0].exists())
            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_safe_print_falls_back_when_console_cannot_encode_unicode(self):
        stream = _GBKLikeStream()

        game_grabber.safe_print("✅ complete", stream=stream)

        self.assertEqual(stream.values, ["? complete\n"])


if __name__ == "__main__":
    unittest.main()
