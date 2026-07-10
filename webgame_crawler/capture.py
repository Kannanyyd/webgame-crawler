from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from .discovery import (
    build_frame_signals,
    is_tracking_url,
    select_game_frames,
    select_game_resources,
)
from .models import CaptureResult, FrameSnapshot, ResourceRecord


class _NetworkActivity:
    def __init__(self):
        self.inflight: set[int] = set()
        self.last_relevant = time.monotonic()

    def started(self, request: Any):
        if request.method.upper() == "GET" and not is_tracking_url(request.url):
            self.inflight.add(id(request))
            self.last_relevant = time.monotonic()

    def finished(self, request: Any):
        request_id = id(request)
        if request_id in self.inflight:
            self.inflight.discard(request_id)
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


def _click_start_control(page: Any):
    pattern = re.compile(r"^(play|play game|run game|start|continue)$", re.IGNORECASE)
    for frame in page.frames:
        if is_tracking_url(frame.url):
            continue
        try:
            control = frame.get_by_role("button", name=pattern).first
            if control.count() and control.is_visible():
                control.click(timeout=1500)
                return
        except Exception:
            pass
        try:
            control = frame.get_by_role("link", name=pattern).first
            if control.count() and control.is_visible():
                control.click(timeout=1500)
                return
        except Exception:
            pass


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


def _snapshot_frames(page: Any) -> list[FrameSnapshot]:
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
        frames.append(
            FrameSnapshot(
                url=url,
                parent_url=parent_url,
                ancestors=_frame_ancestors(frame),
                canvas_count=canvas_count,
                engine=detect_engine(frame),
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

        page.goto(url, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_timeout(max(0, initial_wait_ms))
        _click_start_control(page)
        page.wait_for_timeout(500)
        _focus_canvas(page)
        wait_for_relevant_idle(page, activity, idle_seconds, timeout_seconds)

        frames = _snapshot_frames(page)
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
