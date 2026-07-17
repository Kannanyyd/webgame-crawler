from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .discovery import (
    GAME_EXTENSIONS,
    build_frame_signals,
    is_game_like_resource,
    is_tracking_url,
    select_game_frames,
    select_game_resources,
)
from .models import CaptureResult, FrameSnapshot, ResourceRecord


class _NetworkActivity:
    def __init__(self):
        self.inflight: set[int] = set()
        self.request_frames: dict[int, str] = {}
        self.focused_frames: set[str] | None = None
        self.last_relevant = time.monotonic()

    def started(self, request: Any):
        resource_type = getattr(request, "resource_type", "other")
        static_type = resource_type in {
            "document",
            "script",
            "stylesheet",
            "image",
            "media",
            "font",
        }
        asset_path = urlparse(request.url).path.lower().endswith(GAME_EXTENSIONS)
        if (
            request.method.upper() == "GET"
            and not is_tracking_url(request.url)
            and (static_type or asset_path)
        ):
            request_id = id(request)
            try:
                frame_url = request.frame.url
            except Exception:
                frame_url = ""
            self.request_frames[request_id] = frame_url
            if self.focused_frames is not None and frame_url not in self.focused_frames:
                return
            self.inflight.add(request_id)
            self.last_relevant = time.monotonic()

    def finished(self, request: Any):
        request_id = id(request)
        if request_id in self.inflight:
            self.inflight.discard(request_id)
            self.last_relevant = time.monotonic()
        self.request_frames.pop(request_id, None)

    def focus_frames(self, frame_urls: set[str]):
        self.focused_frames = set(frame_urls)
        self.inflight = {
            request_id
            for request_id in self.inflight
            if self.request_frames.get(request_id) in self.focused_frames
        }
        self.last_relevant = time.monotonic()


def _frame_ancestors(frame: Any) -> tuple[str, ...]:
    ancestors: list[str] = []
    try:
        parent = frame.parent_frame
        while parent is not None:
            if parent.url:
                ancestors.append(parent.url)
            parent = parent.parent_frame
    except Exception:
        pass
    return tuple(ancestors)


def _request_frame(request: Any) -> tuple[str, tuple[str, ...]]:
    try:
        frame = request.frame
        return frame.url, _frame_ancestors(frame)
    except Exception:
        return "", ()


def detect_engine(frame: Any) -> str:
    checks = (
        ("cc", "cocos"),
        ("CocosEngine", "cocos"),
        ("Laya", "laya"),
        ("Laya3D", "laya"),
        ("egret", "egret"),
        ("UnityLoader", "unity"),
        ("createUnityInstance", "unity"),
        ("Phaser", "phaser"),
        ("PIXI", "pixi"),
        ("THREE", "three"),
        ("BABYLON", "babylon"),
        ("createjs", "createjs"),
    )
    for global_name, engine in checks:
        try:
            if frame.evaluate(f"() => typeof window[{global_name!r}] !== 'undefined'"):
                return engine
        except Exception:
            continue

    try:
        sources = frame.locator("script[src]").evaluate_all(
            "els => els.map(el => (el.getAttribute('src') || '').toLowerCase())"
        )
    except Exception:
        sources = []
    joined = "\n".join(sources)
    script_checks = (
        (r"c3(runtime|main)|construct", "construct"),
        (r"unity|build\.loader", "unity"),
        (r"cocos|application\.js", "cocos"),
        (r"laya", "laya"),
        (r"phaser", "phaser"),
        (r"pixi", "pixi"),
        (r"babylon", "babylon"),
    )
    for pattern, engine in script_checks:
        if re.search(pattern, joined):
            return engine

    try:
        if frame.locator("canvas").count() > 0:
            return "html5"
    except Exception:
        pass
    return "unknown"


def wait_for_relevant_idle(
    page: Any,
    activity: _NetworkActivity,
    idle_seconds: float,
    timeout_seconds: float,
    minimum_seconds: float = 0.5,
):
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        elapsed = time.monotonic() - started
        idle_for = time.monotonic() - activity.last_relevant
        if elapsed >= minimum_seconds and not activity.inflight and idle_for >= idle_seconds:
            return
        page.wait_for_timeout(200)


def navigate_page(page: Any, url: str, timeout_ms: int = 60_000) -> str | None:
    try:
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        return None
    except Exception as error:
        return str(error)


STRONG_START_PATTERN = re.compile(
    r"^(play game|play now|start game|launch game|"
    r"现在玩|开始游戏|进入游戏|"
    r"играть сейчас|начать игру|"
    r"jogar agora|iniciar jogo|jugar ahora|iniciar juego|"
    r"şimdi oyna|oyunu başlat|main sekarang|mulai permainan)$",
    re.IGNORECASE,
)
WEAK_START_PATTERN = re.compile(r"^(play|run game|start|continue)$", re.IGNORECASE)


def _click_start_control(page: Any, allow_weak: bool = True) -> bool:
    patterns = (
        (STRONG_START_PATTERN, WEAK_START_PATTERN)
        if allow_weak
        else (STRONG_START_PATTERN,)
    )
    for frame in page.frames:
        if is_tracking_url(frame.url):
            continue
        for pattern in patterns:
            for role in ("button", "link"):
                try:
                    control = frame.get_by_role(role, name=pattern).first
                    if control.count() and control.is_visible():
                        control.click(timeout=1500)
                        return True
                except Exception:
                    pass
    return False


def _wait_for_start_control(
    page: Any, timeout_seconds: float, allow_weak: bool = True
) -> bool:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        if _click_start_control(page, allow_weak=allow_weak):
            return True
        page.wait_for_timeout(250)
    return _click_start_control(page, allow_weak=allow_weak)


def _game_surface_urls(page: Any) -> set[str]:
    urls: set[str] = set()
    for frame in page.frames:
        if is_tracking_url(frame.url):
            continue
        try:
            if frame.locator("canvas").count() > 0:
                urls.add(frame.url)
        except Exception:
            continue
    return urls


def _has_game_surface(page: Any) -> bool:
    return bool(_game_surface_urls(page))


def _wait_for_game_surface(page: Any, timeout_seconds: float) -> bool:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        if _has_game_surface(page):
            return True
        page.wait_for_timeout(250)
    return _has_game_surface(page)


def _focus_canvas(page: Any):
    candidates = []
    for frame in page.frames:
        if is_tracking_url(frame.url):
            continue
        try:
            count = frame.locator("canvas").count()
        except Exception:
            count = 0
        if count:
            candidates.append(frame)
    for frame in candidates:
        try:
            canvas = frame.locator("canvas").first
            if canvas.is_visible():
                canvas.click(position={"x": 2, "y": 2}, force=True, timeout=1000)
                return
        except Exception:
            continue


def _should_detect_engine(
    frame_url: str,
    canvas_count: int,
    game_resource_count: int,
    encoded_size: int,
) -> bool:
    if is_tracking_url(frame_url):
        return False
    if canvas_count > 0:
        return True
    return game_resource_count >= 4 and encoded_size >= 64 * 1024


def _snapshot_frames(page: Any, resources: list[ResourceRecord]) -> list[FrameSnapshot]:
    resource_stats: dict[str, list[int]] = {}
    for resource in resources:
        if not is_game_like_resource(resource):
            continue
        stats = resource_stats.setdefault(resource.frame_url, [0, 0])
        stats[0] += 1
        stats[1] += max(0, resource.encoded_size)

    frames: list[FrameSnapshot] = []
    for frame in page.frames:
        url = frame.url
        if not url:
            continue
        try:
            canvas_count = frame.locator("canvas").count()
        except Exception:
            canvas_count = 0
        parent_url = ""
        try:
            if frame.parent_frame is not None:
                parent_url = frame.parent_frame.url
        except Exception:
            pass
        game_resource_count, encoded_size = resource_stats.get(url, [0, 0])
        engine = (
            detect_engine(frame)
            if _should_detect_engine(
                url, canvas_count, game_resource_count, encoded_size
            )
            else "unknown"
        )
        frames.append(
            FrameSnapshot(
                url=url,
                parent_url=parent_url,
                ancestors=_frame_ancestors(frame),
                canvas_count=canvas_count,
                engine=engine,
            )
        )
    return frames


def capture_game(
    url: str,
    browser_path: str | Path | None = None,
    headless: bool = True,
    initial_wait_ms: int = 2_000,
    idle_seconds: float = 4.0,
    timeout_seconds: float = 45.0,
) -> CaptureResult:
    if browser_path is not None:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)

    from playwright.sync_api import sync_playwright

    resources: list[ResourceRecord] = []
    by_request: dict[int, ResourceRecord] = {}
    activity = _NetworkActivity()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        def on_request(request):
            frame_url, ancestors = _request_frame(request)
            record = ResourceRecord(
                url=request.url,
                method=request.method,
                resource_type=request.resource_type,
                frame_url=frame_url,
                frame_ancestors=ancestors,
                request_headers=dict(request.headers),
            )
            resources.append(record)
            by_request[id(request)] = record
            activity.started(request)

        def on_response(response):
            record = by_request.get(id(response.request))
            if record is None:
                return
            record.status = response.status
            record.response_headers = dict(response.headers)
            try:
                record.encoded_size = int(response.headers.get("content-length", "0"))
            except ValueError:
                record.encoded_size = 0
            if record.resource_type == "document":
                record.frame_url = response.url

        def on_failed(request):
            record = by_request.get(id(request))
            if record is not None:
                record.failure = request.failure or "request failed"
            activity.finished(request)

        context.on("request", on_request)
        context.on("response", on_response)
        context.on("requestfinished", activity.finished)
        context.on("requestfailed", on_failed)

        navigate_page(page, url)
        page.wait_for_timeout(max(0, initial_wait_ms))
        has_surface = _wait_for_game_surface(page, min(10.0, timeout_seconds / 2))
        clicked_start = _click_start_control(page, allow_weak=not has_surface)
        if not clicked_start and not has_surface:
            clicked_start = _wait_for_start_control(
                page,
                min(5.0, timeout_seconds / 3),
                allow_weak=True,
            )
        if clicked_start or not has_surface:
            has_surface = _wait_for_game_surface(page, min(5.0, timeout_seconds / 3))
        if has_surface:
            activity.focus_frames(_game_surface_urls(page))
            _focus_canvas(page)
        minimum_observation = (
            min(15.0, max(2.0, timeout_seconds / 3)) if clicked_start else 0.5
        )
        wait_for_relevant_idle(
            page,
            activity,
            idle_seconds,
            timeout_seconds,
            minimum_seconds=minimum_observation,
        )

        frames = _snapshot_frames(page, resources)
        signals = build_frame_signals(frames, resources)
        selected_frames = select_game_frames(signals)
        selected_urls = {signal.frame.url for signal in selected_frames}
        selected_resources = select_game_resources(resources, selected_urls)
        title = page.title() or "game"
        final_url = page.url
        cookies = context.cookies()
        user_agent = page.evaluate("() => navigator.userAgent")
        browser.close()

    return CaptureResult(
        requested_url=url,
        final_url=final_url,
        title=title,
        frames=frames,
        resources=resources,
        selected_frames=selected_frames,
        selected_resources=selected_resources,
        cookies=cookies,
        user_agent=user_agent,
    )
