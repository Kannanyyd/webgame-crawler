from __future__ import annotations

from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class _FixtureServer:
    def __init__(self, handler_factory):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self):
        return self.server.server_address[1]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class GameFixture:
    def __init__(self):
        self.stack = ExitStack()
        self.asset_server = None
        self.portal_server = None

    def __enter__(self):
        fixture = self

        class AssetHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == "/game.data?token=abc":
                    body = b"fixture-game-binary"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/late.bundle":
                    body = b"fixture-late-game-binary"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)

        self.asset_server = self.stack.enter_context(_FixtureServer(AssetHandler))

        class PortalHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _html(self, text):
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/portal":
                    self._html(
                        "<title>Fixture Game</title>"
                        "<button onclick=\"fetch('/video-player')\">Play</button>"
                        "<button onclick=\"document.getElementById('game-frame').contentWindow.postMessage('start', '*')\">Play game</button>"
                        "<iframe src='/ad?url=https%3A%2F%2Fgames.example%2Findex.html'></iframe>"
                        "<iframe id='game-frame' src='/game'></iframe>"
                    )
                    return
                if self.path == "/video-player":
                    body = b"video"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path.startswith("/ad?"):
                    self._html("<img src='/pixel.gif'>")
                    return
                if self.path == "/pixel.gif":
                    body = b"x"
                    self.send_response(200)
                    self.send_header("Content-Type", "image/gif")
                    self.send_header("Content-Length", "1")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/game":
                    self._html(
                        "<canvas id='game'></canvas>"
                        "<script>"
                        "fetch('http://127.0.0.1:%d/game.data?token=abc');"
                        "addEventListener('message', event => {"
                        "if (event.data === 'start') setTimeout(() => "
                        "fetch('http://127.0.0.1:%d/late.bundle'), 1200);"
                        "});"
                        "</script>"
                        % (fixture.asset_server.port, fixture.asset_server.port)
                    )
                    return
                self.send_error(404)

        self.portal_server = self.stack.enter_context(_FixtureServer(PortalHandler))
        return self

    def __exit__(self, *args):
        self.stack.__exit__(*args)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.portal_server.port}/portal"

    @property
    def game_url(self):
        return f"http://127.0.0.1:{self.portal_server.port}/game"

    @property
    def asset_url(self):
        return f"http://127.0.0.1:{self.asset_server.port}/game.data?token=abc"

    @property
    def late_asset_url(self):
        return f"http://127.0.0.1:{self.asset_server.port}/late.bundle"
