from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .capture import _NetworkActivity, _game_surface_urls, drive_game_page
from .discovery import is_game_like_resource, is_tracking_url
from .har import inspect_har
from .models import CaptureResult, ReplayFailure, ReplaySummary, ResourceRecord


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)

_STATIC_RESOURCE_TYPES = {
    "document",
    "script",
    "stylesheet",
    "image",
    "media",
    "font",
}


def _request_frame_url(request: Any) -> str:
    try:
        return request.frame.url
    except Exception:
        return ""


def is_required_replay_failure(request: Any, capture: CaptureResult) -> bool:
    method = request.method
    url = request.url
    resource_type = request.resource_type
    if method.upper() != "GET" or is_tracking_url(url):
        return False

    selected_resource_urls = {resource.url for resource in capture.selected_resources}
    if url in selected_resource_urls:
        return True

    selected_frame_urls = {signal.frame.url for signal in capture.selected_frames}
    frame_url = _request_frame_url(request)
    if frame_url not in selected_frame_urls:
        return False
    if resource_type in _STATIC_RESOURCE_TYPES:
        return True
    return is_game_like_resource(
        ResourceRecord(url=url, method=method, resource_type=resource_type)
    )


def verify_replay(
    har_path: Path,
    capture: CaptureResult,
    browser_path: str | Path | None = None,
    headless: bool = True,
    timeout_seconds: float = 20.0,
) -> ReplaySummary:
    archive = inspect_har(har_path)
    if not archive.valid:
        return ReplaySummary(
            archive=archive,
            requested_url=capture.requested_url,
            error=archive.error,
        )

    if browser_path is not None:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)

    from playwright.sync_api import sync_playwright

    failures: list[ReplayFailure] = []
    final_url = ""
    reached_game_surface = False
    replay_error: str | None = None
    activity = _NetworkActivity()
    selected_frame_urls = {signal.frame.url for signal in capture.selected_frames}
    engine_frame_urls = {
        signal.frame.url
        for signal in capture.selected_frames
        if signal.frame.canvas_count == 0 and signal.frame.engine != "unknown"
    }
    loaded_documents: set[str] = set()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=capture.user_agent or DEFAULT_USER_AGENT,
                    service_workers="block",
                )
                try:
                    context.route_from_har(str(har_path), not_found="abort")
                    page = context.new_page()

                    def on_request_failed(request: Any) -> None:
                        nonlocal replay_error
                        error = request.failure or "request not found in HAR"
                        failures.append(
                            ReplayFailure(
                                url=request.url,
                                method=request.method,
                                resource_type=request.resource_type,
                                frame_url=_request_frame_url(request),
                                error=error,
                                required=is_required_replay_failure(request, capture),
                            )
                        )
                        activity.finished(request)
                        if (
                            request.resource_type == "document"
                            and request.url == capture.requested_url
                        ):
                            replay_error = error

                    def on_request_finished(request: Any) -> None:
                        if request.resource_type == "document":
                            loaded_documents.add(request.url)
                        activity.finished(request)

                    context.on("request", activity.started)
                    context.on("requestfinished", on_request_finished)
                    context.on("requestfailed", on_request_failed)

                    try:
                        drive_game_page(
                            page,
                            capture.requested_url,
                            activity,
                            initial_wait_ms=250,
                            idle_seconds=0.5,
                            timeout_seconds=timeout_seconds,
                        )
                        final_url = page.url
                        canvas_frame_urls = _game_surface_urls(page)
                        reached_game_surface = bool(
                            canvas_frame_urls & selected_frame_urls
                            or loaded_documents & engine_frame_urls
                        )
                    except Exception as error:
                        replay_error = str(error)
                        try:
                            final_url = page.url
                        except Exception:
                            pass
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as error:
        replay_error = str(error)

    return ReplaySummary(
        archive=archive,
        requested_url=capture.requested_url,
        final_url=final_url,
        reached_game_surface=reached_game_surface,
        failures=failures,
        error=replay_error,
    )
