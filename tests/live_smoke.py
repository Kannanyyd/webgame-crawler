"""Opt-in live crawler checks. This module is not part of unittest discovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from webgame_crawler.capture import capture_game
from webgame_crawler.discovery import is_tracking_url
from webgame_crawler.models import CaptureResult


PROJECT_DIR = Path(__file__).resolve().parents[1]


def summarize_capture(capture: CaptureResult) -> dict:
    return {
        "url": capture.requested_url,
        "title": capture.title,
        "selectedFrames": [signal.frame.url for signal in capture.selected_frames],
        "engines": sorted({signal.frame.engine for signal in capture.selected_frames}),
        "capturedRequests": len(capture.resources),
        "selectedResources": len(capture.selected_resources),
        "encodedBytes": sum(resource.encoded_size for resource in capture.selected_resources),
        "resourceHosts": sorted(
            {urlparse(resource.url).netloc for resource in capture.selected_resources}
        ),
        "largestResources": [
            {"url": resource.url, "bytes": resource.encoded_size}
            for resource in sorted(
                capture.selected_resources,
                key=lambda item: item.encoded_size,
                reverse=True,
            )[:10]
        ],
    }


def validate_capture(capture: CaptureResult) -> list[str]:
    errors: list[str] = []
    if not capture.selected_frames:
        errors.append("no game context selected")
        return errors
    for signal in capture.selected_frames:
        if is_tracking_url(signal.frame.url):
            errors.append(f"tracking frame selected: {signal.frame.url}")
    if not capture.selected_resources:
        errors.append("no game resources selected")

    engines = {signal.frame.engine for signal in capture.selected_frames}
    paths = [urlparse(resource.url).path.lower() for resource in capture.selected_resources]
    if "unity" in engines:
        if not any(".data" in path or path.endswith(".unityweb") for path in paths):
            errors.append("Unity data resource was not selected")
        if not any(".wasm" in path or path.endswith(".unityweb") for path in paths):
            errors.append("Unity WASM resource was not selected")
    if "construct" in engines and not any(path.endswith("data.json") for path in paths):
        errors.append("Construct data.json was not selected")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run opt-in live webgame capture checks")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args(argv)

    exit_code = 0
    for url in args.urls:
        capture = capture_game(
            url,
            browser_path=PROJECT_DIR / ".pw-browsers",
            headless=not args.headed,
            initial_wait_ms=2_000,
            idle_seconds=3.0,
            timeout_seconds=35.0,
        )
        summary = summarize_capture(capture)
        errors = validate_capture(capture)
        summary["errors"] = errors
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if errors:
            exit_code = 1
        if args.download:
            from game_grabber import run

            exit_code = max(exit_code, run(url))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
