from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from .models import FrameSignal, FrameSnapshot, ResourceRecord


TRACKING_HOST_SUFFIXES = (
    "doubleclick.net",
    "googlesyndication.com",
    "googletagmanager.com",
    "google-analytics.com",
    "amazon-adsystem.com",
    "adnxs.com",
    "casalemedia.com",
    "criteo.com",
    "pubmatic.com",
    "rubiconproject.com",
    "rlcdn.com",
    "bidswitch.net",
    "scorecardresearch.com",
    "quantserve.com",
    "taboola.com",
    "outbrain.com",
    "adtrafficquality.google",
    "fundingchoicesmessages.google",
)

TRACKING_HOST_LABELS = {
    "ad",
    "ads",
    "analytics",
    "pixel",
    "pixels",
    "tracking",
    "telemetry",
    "counter",
    "metrics",
    "usersync",
}

TRACKING_HOST_MARKERS = (
    "advert",
    "afvert",
    "adserver",
    "creativecdn",
    "privacymanager",
    "crwdcntrl",
    "openx",
    "fundingchoicesmessages",
)

GAME_EXTENSIONS = (
    ".html",
    ".htm",
    ".js",
    ".mjs",
    ".css",
    ".json",
    ".wasm",
    ".data",
    ".bin",
    ".br",
    ".gz",
    ".unityweb",
    ".pck",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".webm",
    ".mp4",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".atlas",
    ".fnt",
    ".xml",
    ".glb",
    ".gltf",
    ".ktx2",
    ".basis",
    ".dds",
    ".lh",
    ".ls",
    ".lm",
    ".lmat",
    ".lav",
    ".ani",
    ".sk",
    ".scene",
    ".prefab",
)

GAME_RESOURCE_TYPES = {
    "document",
    "script",
    "stylesheet",
    "image",
    "media",
    "font",
    "fetch",
    "xhr",
    "other",
}


def hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_tracking_url(url: str) -> bool:
    host = hostname(url)
    if not host:
        return False
    if any(host == suffix or host.endswith("." + suffix) for suffix in TRACKING_HOST_SUFFIXES):
        return True
    if any(marker in host for marker in TRACKING_HOST_MARKERS):
        return True
    return any(label in TRACKING_HOST_LABELS for label in host.split("."))


def is_game_like_resource(resource: ResourceRecord) -> bool:
    if resource.method.upper() != "GET" or is_tracking_url(resource.url):
        return False
    if resource.status not in (None, 200, 206, 304):
        return False
    path = urlparse(resource.url).path.lower()
    content_type = resource.response_headers.get("content-type", "").lower()
    return (
        resource.resource_type in GAME_RESOURCE_TYPES
        and (
            path.endswith(GAME_EXTENSIONS)
            or content_type.startswith(("image/", "audio/", "video/", "font/"))
            or "javascript" in content_type
            or "json" in content_type
            or "wasm" in content_type
            or "octet-stream" in content_type
            or resource.resource_type in {"document", "script", "stylesheet", "image", "media", "font"}
        )
    )


def build_frame_signals(
    frames: Iterable[FrameSnapshot], resources: Iterable[ResourceRecord]
) -> list[FrameSignal]:
    frame_list = list(frames)
    signals = {frame.url: FrameSignal(frame=frame) for frame in frame_list if frame.url}

    for resource in resources:
        signal = signals.get(resource.frame_url)
        if signal is None:
            continue
        signal.resource_count += 1
        signal.encoded_size += max(0, resource.encoded_size)
        if is_game_like_resource(resource):
            signal.game_like_count += 1

    for signal in signals.values():
        frame = signal.frame
        if is_tracking_url(frame.url):
            signal.score = -10_000.0
            continue
        score = float(frame.canvas_count * 120)
        if frame.engine != "unknown":
            score += 80
        score += min(signal.game_like_count * 3, 75)
        score += min(signal.encoded_size / (256 * 1024), 120)
        if urlparse(frame.url).scheme in {"http", "https"}:
            score += 5
        signal.score = score

    return sorted(signals.values(), key=lambda signal: signal.score, reverse=True)


def select_game_frames(signals: Iterable[FrameSignal]) -> list[FrameSignal]:
    candidates = [signal for signal in signals if signal.score > 0 and not is_tracking_url(signal.frame.url)]
    if not candidates:
        return []
    candidates = [
        signal
        for signal in candidates
        if signal.frame.canvas_count > 0 or signal.frame.engine != "unknown"
    ]
    if not candidates:
        return []
    top_score = candidates[0].score
    threshold = max(20.0, top_score * 0.55)
    selected = [signal for signal in candidates if signal.score >= threshold]
    canvas_selected = [signal for signal in selected if signal.frame.canvas_count > 0]
    return canvas_selected or selected[:3]


def select_game_resources(
    resources: Iterable[ResourceRecord], selected_frame_urls: set[str]
) -> list[ResourceRecord]:
    selected: list[ResourceRecord] = []
    seen: set[str] = set()
    for resource in resources:
        belongs_to_game = resource.frame_url in selected_frame_urls or any(
            ancestor in selected_frame_urls for ancestor in resource.frame_ancestors
        )
        if not belongs_to_game or not is_game_like_resource(resource):
            continue
        if resource.url in seen:
            continue
        seen.add(resource.url)
        selected.append(resource)
    return selected
