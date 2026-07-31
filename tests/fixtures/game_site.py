from __future__ import annotations

from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from threading import Event, Lock, Thread


class _CountingHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_factory):
        self._connection_lock = Lock()
        self.accepted_connections = 0
        super().__init__(server_address, handler_factory)

    def get_request(self):
        request = super().get_request()
        with self._connection_lock:
            self.accepted_connections += 1
        return request

    def reset_connections(self):
        with self._connection_lock:
            self.accepted_connections = 0


class _DatagramCounter:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.settimeout(0.1)
        self._count_lock = Lock()
        self._count = 0
        self._stop = Event()
        self.thread = Thread(target=self._receive, daemon=True)

    @property
    def port(self):
        return self.socket.getsockname()[1]

    @property
    def count(self):
        with self._count_lock:
            return self._count

    def reset(self):
        with self._count_lock:
            self._count = 0

    def _receive(self):
        while not self._stop.is_set():
            try:
                self.socket.recvfrom(65_535)
            except socket.timeout:
                continue
            except OSError:
                return
            with self._count_lock:
                self._count += 1

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self.socket.close()
        self.thread.join(timeout=2)


class _FixtureServer:
    def __init__(self, handler_factory):
        self.server = _CountingHTTPServer(("127.0.0.1", 0), handler_factory)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self):
        return self.server.server_address[1]

    @property
    def accepted_connections(self):
        return self.server.accepted_connections

    def reset_connections(self):
        self.server.reset_connections()

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
        self.datagram_counter = None

    def __enter__(self):
        fixture = self
        self.datagram_counter = self.stack.enter_context(_DatagramCounter())

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
                        "<script>fetch('/analytics?nonce=' + crypto.randomUUID())</script>"
                        "<button onclick=\"fetch('/video-player')\">Play</button>"
                        "<button onclick=\"document.getElementById('game-frame').contentWindow.postMessage('start', '*')\">Play game</button>"
                        "<iframe src='/ad?url=https%3A%2F%2Fgames.example%2Findex.html'></iframe>"
                        "<iframe id='game-frame' src='/game'></iframe>"
                    )
                    return
                if self.path.startswith("/analytics?nonce="):
                    self.send_response(204)
                    self.end_headers()
                    return
                if self.path == "/delayed-portal":
                    self._html(
                        "<title>Delayed Fixture Game</title>"
                        "<script>"
                        "setTimeout(() => {"
                        "const button = document.createElement('button');"
                        "button.textContent = 'Play game';"
                        "button.onclick = () => {"
                        "const frame = document.createElement('iframe');"
                        "frame.src = '/game';"
                        "document.body.appendChild(frame);"
                        "};"
                        "document.body.appendChild(button);"
                        "}, 3500);"
                        "</script>"
                    )
                    return
                if self.path == "/auto-delayed-game":
                    self._html(
                        "<title>Auto-delayed Fixture Game</title>"
                        "<canvas id='game'></canvas>"
                        "<script>setTimeout(() => fetch('http://127.0.0.1:%d/late.bundle'), 1200)</script>"
                        % fixture.asset_server.port
                    )
                    return
                if self.path == "/network-probe":
                    self._html(
                        "<title>Network Isolation Fixture</title>"
                        "<canvas id='game'></canvas>"
                        "<script>"
                        "window.probeSocket = new WebSocket('ws://127.0.0.1:%d/socket');"
                        "window.probePeer = new RTCPeerConnection({iceServers: [{urls: 'stun:127.0.0.1:%d'}]});"
                        "window.probePeer.createDataChannel('probe');"
                        "window.probePeer.createOffer().then(offer => window.probePeer.setLocalDescription(offer));"
                        "</script>"
                        % (fixture.portal_server.port, fixture.datagram_counter.port)
                    )
                    return
                if self.path == "/nested-game":
                    self._html(
                        "<title>Nested Fixture Game</title>"
                        "<canvas id='game'></canvas>"
                        "<iframe src='/nested-child'></iframe>"
                    )
                    return
                if self.path == "/nested-child":
                    self._html(
                        "<script>"
                        "const script = document.createElement('script');"
                        "script.src = '/runtime.js?nonce=' + crypto.randomUUID();"
                        "document.head.appendChild(script);"
                        "</script>"
                    )
                    return
                if self.path.startswith("/runtime.js?nonce="):
                    body = b"window.nestedRuntimeLoaded = true;"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/javascript")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/socket":
                    self.send_error(426)
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
    def delayed_url(self):
        return f"http://127.0.0.1:{self.portal_server.port}/delayed-portal"

    @property
    def auto_delayed_url(self):
        return f"http://127.0.0.1:{self.portal_server.port}/auto-delayed-game"

    @property
    def network_probe_url(self):
        return f"http://127.0.0.1:{self.portal_server.port}/network-probe"

    @property
    def nested_game_url(self):
        return f"http://127.0.0.1:{self.portal_server.port}/nested-game"

    @property
    def nested_child_url(self):
        return f"http://127.0.0.1:{self.portal_server.port}/nested-child"

    @property
    def live_tcp_connections(self):
        return (
            self.portal_server.accepted_connections
            + self.asset_server.accepted_connections
        )

    @property
    def live_udp_datagrams(self):
        return self.datagram_counter.count

    def reset_live_network_counts(self):
        self.portal_server.reset_connections()
        self.asset_server.reset_connections()
        self.datagram_counter.reset()

    @property
    def asset_url(self):
        return f"http://127.0.0.1:{self.asset_server.port}/game.data?token=abc"

    @property
    def late_asset_url(self):
        return f"http://127.0.0.1:{self.asset_server.port}/late.bundle"
