"""Discover and download resources required to reach a playable web-game screen."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, TextIO
from urllib.parse import urlparse

from webgame_crawler.capture import capture_game
from webgame_crawler.download import (
    build_session,
    download_resources,
    fetch_text,
    probe_resource_urls,
)
from webgame_crawler.manifests import supplement_resources
from webgame_crawler.models import CaptureResult, DownloadSummary
from webgame_crawler.report import write_reports


PROJECT_DIR = Path(__file__).resolve().parent
PW_BROWSERS_PATH = PROJECT_DIR / ".pw-browsers"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PW_BROWSERS_PATH))


def safe_print(message: str = "", stream: TextIO | None = None):
    stream = stream or sys.stdout
    text = str(message) + "\n"
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        fallback = text.encode(encoding, errors="replace").decode(encoding)
        stream.write(fallback)
    stream.flush()


def safe_game_name(title: str) -> str:
    title = re.sub(r"\s*🕹️?\s*Play on .*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    return title or "game"


def ensure_browser(browser_path: Path = PW_BROWSERS_PATH):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if executable.exists():
        return
    safe_print("Playwright Chromium is missing; installing the required revision...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        env=os.environ.copy(),
    )


def _print_capture_summary(capture: CaptureResult, printer: Callable[[str], None]):
    printer(f"Captured requests: {len(capture.resources)}")
    if not capture.selected_frames:
        printer("No confident game context was found.")
        return
    for signal in capture.selected_frames:
        printer(
            "Game context: "
            f"engine={signal.frame.engine} score={signal.score:.1f} "
            f"resources={signal.resource_count} bytes={signal.encoded_size} "
            f"url={signal.frame.url}"
        )


def run(
    url: str,
    *,
    output_root: Path = PROJECT_DIR,
    capture_func=capture_game,
    download_func=download_resources,
    printer: Callable[[str], None] = safe_print,
) -> int:
    if capture_func is capture_game:
        ensure_browser()

    printer(f"Loading: {url}")
    capture = capture_func(url, browser_path=PW_BROWSERS_PATH, headless=True)
    _print_capture_summary(capture, printer)
    if not capture.selected_frames or not capture.selected_resources:
        return 2

    session = build_session(capture.cookies, capture.user_agent)
    frame_engines = {
        signal.frame.url: signal.frame.engine for signal in capture.selected_frames
    }
    supplemental = supplement_resources(
        capture.selected_resources,
        frame_engines,
        lambda source_url, headers: fetch_text(session, source_url, headers),
        probe_urls=lambda urls, headers: probe_resource_urls(session, urls, headers),
    )
    resources = capture.selected_resources + supplemental

    game_name = safe_game_name(capture.title)
    output_dir = output_root / game_name
    main_host = urlparse(capture.selected_frames[0].frame.url).netloc
    printer(
        f"Included resources: {len(resources)} "
        f"(browser={len(capture.selected_resources)}, manifest={len(supplemental)})"
    )
    downloads: DownloadSummary = download_func(
        resources,
        capture.cookies,
        output_dir,
        main_host,
        user_agent=capture.user_agent,
    )
    summary = write_reports(capture, resources, downloads, output_dir)
    printer(
        f"Downloaded={summary['downloaded']} Failed={summary['failed']} "
        f"Required failed={summary['requiredFailed']} "
        f"Encoded={summary['encodedBytes'] / 1024 / 1024:.2f} MB "
        f"Known decoded={summary['knownDecodedBytes'] / 1024 / 1024:.2f} MB"
    )
    printer(f"Output: {output_dir}")
    return 1 if downloads.required_failed else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        url = argv[0].strip()
    else:
        url = input("Game page URL: ").strip()
    if not url.startswith(("http://", "https://")):
        safe_print("A valid http(s) URL is required.")
        return 2
    try:
        return run(url)
    except KeyboardInterrupt:
        safe_print("Interrupted.")
        return 130
    except Exception as error:
        safe_print(f"Crawl failed: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
