from __future__ import annotations

import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from webgame_crawler.download import download_resources, resource_local_path
from webgame_crawler.models import ResourceRecord


class _DownloadHandler(BaseHTTPRequestHandler):
    raw_br = b"not-decoded-brotli-bytes"
    flaky_attempts = 0

    def log_message(self, *_):
        pass

    def _send(self, body, status=200, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/protected.bin":
            if "session=ok" not in self.headers.get("Cookie", ""):
                self._send(b"forbidden", status=403)
            else:
                self._send(b"cookie-data")
            return
        if self.path == "/variant.bin?v=1":
            self._send(b"variant-one")
            return
        if self.path == "/variant.bin?v=2":
            self._send(b"variant-two")
            return
        if self.path == "/partial.bin":
            body = b"complete"
            self._send(body, status=206, headers={"Content-Range": "bytes 0-7/8"})
            return
        if self.path == "/asset.data.br":
            self._send(self.raw_br, headers={"Content-Encoding": "br"})
            return
        if self.path == "/flaky.bin":
            type(self).flaky_attempts += 1
            if type(self).flaky_attempts == 1:
                self._send(b"retry", status=503)
            else:
                self._send(b"recovered")
            return
        self._send(b"missing", status=404)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _DownloadHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = f"127.0.0.1:{cls.server.server_address[1]}"
        cls.base = "http://" + cls.host

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_query_variants_map_to_distinct_paths(self):
        first = resource_local_path(self.base + "/variant.bin?v=1", self.host)
        second = resource_local_path(self.base + "/variant.bin?v=2", self.host)

        self.assertNotEqual(first, second)
        self.assertEqual(first.suffix, ".bin")
        self.assertEqual(second.suffix, ".bin")

    def test_download_reuses_cookie_accepts_complete_206_and_keeps_raw_br(self):
        urls = [
            self.base + "/protected.bin",
            self.base + "/variant.bin?v=1",
            self.base + "/variant.bin?v=2",
            self.base + "/partial.bin",
            self.base + "/asset.data.br",
        ]
        resources = [ResourceRecord(url=url, status=200) for url in urls]
        cookies = [
            {
                "name": "session",
                "value": "ok",
                "domain": "127.0.0.1",
                "path": "/",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            summary = download_resources(
                resources,
                cookies,
                Path(temp_dir),
                self.host,
                max_workers=3,
            )
            by_url = {result.url: result for result in summary.results}

            self.assertEqual(summary.failed, 0)
            self.assertEqual(by_url[self.base + "/protected.bin"].local_path.read_bytes(), b"cookie-data")
            self.assertEqual(by_url[self.base + "/partial.bin"].local_path.read_bytes(), b"complete")
            self.assertEqual(
                by_url[self.base + "/asset.data.br"].local_path.read_bytes(),
                _DownloadHandler.raw_br,
            )
            first = by_url[self.base + "/variant.bin?v=1"].local_path
            second = by_url[self.base + "/variant.bin?v=2"].local_path
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), b"variant-one")
            self.assertEqual(second.read_bytes(), b"variant-two")

    def test_download_retries_transient_server_failure(self):
        _DownloadHandler.flaky_attempts = 0
        resource = ResourceRecord(url=self.base + "/flaky.bin", status=200)
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = download_resources(
                [resource], [], Path(temp_dir), self.host, max_workers=1
            )

        self.assertEqual(summary.failed, 0)
        self.assertEqual(_DownloadHandler.flaky_attempts, 2)


if __name__ == "__main__":
    unittest.main()
