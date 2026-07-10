# Generic Web Game Resource Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace portal-domain guessing with a browser-derived resource graph that captures the static resources required to reach a playable web-game screen.

**Architecture:** Keep `game_grabber.py` as the compatible CLI and move capture, scoring, manifest discovery, authenticated downloading, and reporting into a small `webgame_crawler` package. Playwright frame/request relationships are authoritative; Unity, Construct, Cocos, Laya, and generic HTML5 parsing only supplement resources that were not observed.

**Tech Stack:** Python 3.11+, Playwright sync API, Requests, standard-library `unittest`, dataclasses, urllib.

## Global Constraints

- Preserve `python game_grabber.py <url>`.
- Do not add portal-specific resource allowlists.
- Never remove query parameters from discovery keys.
- Do not restrict game resources to a shared root domain.
- Reuse browser cookies and safe captured headers for downloads.
- Support HTTP 200 and valid 206 responses.
- Store encoded `.br`/`.gz` bytes without transparent decompression.
- Do not bypass authentication, CAPTCHA, payment, DRM, or access controls.
- Keep live portal tests opt-in; deterministic tests must run locally.

---

### Task 1: Resource models and game-context scoring

**Files:**
- Create: `webgame_crawler/__init__.py`
- Create: `webgame_crawler/models.py`
- Create: `webgame_crawler/discovery.py`
- Create: `tests/__init__.py`
- Create: `tests/test_discovery.py`

**Interfaces:**
- Produces: `ResourceRecord`, `FrameSnapshot`, `FrameSignal`, `CaptureResult` dataclasses.
- Produces: `is_tracking_url(url)`, `build_frame_signals(frames, resources)`, `select_game_frames(signals)`, and `select_game_resources(resources, selected_urls)`.

- [ ] **Step 1: Write failing discovery tests**

Tests must assert that a DoubleClick frame whose query contains `crazygames.com` is rejected, a canvas frame with large WASM/data traffic wins, exact query variants remain distinct, and a cross-domain asset initiated by the selected frame is retained.

- [ ] **Step 2: Run the discovery tests and verify RED**

Run: `py -3.12 -m unittest tests.test_discovery -v`

Expected: import failure because `webgame_crawler.discovery` does not exist.

- [ ] **Step 3: Implement the dataclasses and pure scoring functions**

`ResourceRecord` must retain exact URL, method, resource type, frame URL, frame ancestors, request headers, response headers, status, encoded size, failure, and discovery method. Scoring must use parsed hostnames, canvas count, engine signal, game-like resource count, and encoded bytes. It must never inspect query text for hostname keywords.

- [ ] **Step 4: Run the discovery tests and verify GREEN**

Run: `py -3.12 -m unittest tests.test_discovery -v`

Expected: all discovery tests pass.

- [ ] **Step 5: Commit the scoring milestone**

```powershell
git add webgame_crawler tests
git commit -m "feat: score game contexts from browser evidence"
```

### Task 2: Browser capture and condition-based settling

**Files:**
- Create: `webgame_crawler/capture.py`
- Create: `tests/fixtures/game_site.py`
- Create: `tests/test_capture.py`

**Interfaces:**
- Consumes: model and discovery functions from Task 1.
- Produces: `capture_game(url, browser_path, headless=True) -> CaptureResult`.
- Produces: `detect_engine(frame) -> str` and `wait_for_relevant_idle(page, activity, idle_seconds, timeout_seconds)`.

- [ ] **Step 1: Write a failing browser fixture test**

The fixture must serve a portal page containing an ad iframe whose query mentions a game domain and a real child frame containing a canvas. The real frame must request a binary file from a second local port. The assertion must require selection of the canvas frame and inclusion of the cross-origin binary.

- [ ] **Step 2: Run the capture test and verify RED**

Run: `py -3.12 -m unittest tests.test_capture -v`

Expected: import failure because `capture_game` does not exist.

- [ ] **Step 3: Implement Playwright capture**

Attach request, response, request-finished, and request-failed listeners before navigation. Retain document requests, frame ancestry, exact URLs, safe headers, statuses, and content lengths. Perform one conservative Play-button click, inspect all frames for canvas/engine evidence, optionally focus the strongest canvas, and stop after relevant network activity is idle rather than after a fixed 20-second sleep.

- [ ] **Step 4: Run capture tests and verify GREEN**

Run: `py -3.12 -m unittest tests.test_capture -v`

Expected: the real frame wins and the cross-origin resource is selected.

- [ ] **Step 5: Commit the capture milestone**

```powershell
git add webgame_crawler/capture.py tests/fixtures tests/test_capture.py
git commit -m "feat: capture browser resource relationships"
```

### Task 3: Generic and engine-manifest supplementation

**Files:**
- Create: `webgame_crawler/manifests.py`
- Create: `tests/test_manifests.py`

**Interfaces:**
- Consumes: selected `ResourceRecord` values and a `fetch_text(url, headers)` callback.
- Produces: `extract_resource_urls(text, source_url, engine="unknown") -> set[str]`.
- Produces: `supplement_resources(resources, engines, fetch_text) -> list[ResourceRecord]`.

- [ ] **Step 1: Write failing manifest tests**

Cover correct resolution beside `index.html`, Unity `dataUrl/frameworkUrl/codeUrl`, Construct `data.json` WebM/WASM references, Cocos bundle paths, Laya `.atlas/.lh/.ls/.lmat/.ani/.sk` references, and generic `.webm/.mp4/.ktx2/.basis/.pck/.br/.gz` resources.

- [ ] **Step 2: Run manifest tests and verify RED**

Run: `py -3.12 -m unittest tests.test_manifests -v`

Expected: import failure because `webgame_crawler.manifests` does not exist.

- [ ] **Step 3: Implement bounded manifest extraction**

Resolve every reference against the containing source URL. Parse quoted resource strings and URL-valued engine configuration fields. Scan only selected HTML, CSS, JavaScript, and JSON resources, cap text response size, and deduplicate by full URL.

- [ ] **Step 4: Run manifest tests and verify GREEN**

Run: `py -3.12 -m unittest tests.test_manifests -v`

Expected: all engine and generic extraction tests pass.

- [ ] **Step 5: Commit the manifest milestone**

```powershell
git add webgame_crawler/manifests.py tests/test_manifests.py
git commit -m "feat: supplement lazy engine resources"
```

### Task 4: Session-faithful streaming downloader

**Files:**
- Create: `webgame_crawler/download.py`
- Create: `tests/test_download.py`

**Interfaces:**
- Consumes: selected and supplemental `ResourceRecord` values plus browser cookies.
- Produces: `resource_local_path(url, main_host) -> Path`.
- Produces: `download_resources(resources, cookies, output_dir, main_host) -> DownloadSummary`.

- [ ] **Step 1: Write failing HTTP download tests**

Use a local HTTP server to require a cookie, expose two query variants of one path, return a complete 206 body, and serve a Brotli-labeled raw byte sequence. Assert distinct files, cookie reuse, accepted 206, and byte-for-byte storage.

- [ ] **Step 2: Run download tests and verify RED**

Run: `py -3.12 -m unittest tests.test_download -v`

Expected: import failure because `webgame_crawler.download` does not exist.

- [ ] **Step 3: Implement streaming and validation**

Seed a Requests session with browser cookies. Replay only safe request headers, remove `Host`, `Content-Length`, `Range`, and browser transport headers, stream with `response.raw.decode_content = False`, accept 200 and complete 206 responses, validate declared lengths, use temporary `.part` files, and hash query strings into collision-safe filenames.

- [ ] **Step 4: Run download tests and verify GREEN**

Run: `py -3.12 -m unittest tests.test_download -v`

Expected: all download fidelity tests pass.

- [ ] **Step 5: Commit the downloader milestone**

```powershell
git add webgame_crawler/download.py tests/test_download.py
git commit -m "feat: download resources with browser session fidelity"
```

### Task 5: CLI orchestration and audit report

**Files:**
- Create: `webgame_crawler/report.py`
- Modify: `game_grabber.py`
- Modify: `README.md`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: capture, selection, supplementation, and download APIs.
- Produces: compatible CLI execution and `_crawl/resource-map.json`, `_crawl/summary.json`, `_crawl/failures.json`.

- [ ] **Step 1: Write failing CLI tests**

Patch only the external browser boundary and assert URL parsing, non-zero exit for incomplete required resources, Unicode-safe fallback output, and JSON summary fields for captured, included, excluded, downloaded, failed, encoded bytes, and known decoded bytes.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `py -3.12 -m unittest tests.test_cli -v`

Expected: failure because the current monolithic CLI does not expose the new orchestration/report API.

- [ ] **Step 3: Replace the monolithic flow with package orchestration**

Keep the same command syntax, use the page title for the output directory, print selected frame confidence and byte totals, write audit JSON, and report compressed and decoded sizes separately. Browser installation checks must verify the expected executable and error messages must remain printable on GBK consoles.

- [ ] **Step 4: Run all deterministic tests and verify GREEN**

Run: `py -3.12 -m unittest discover -s tests -v`

Expected: all deterministic tests pass without network access.

- [ ] **Step 5: Commit the integrated CLI milestone**

```powershell
git add game_grabber.py README.md webgame_crawler/report.py tests/test_cli.py
git commit -m "feat: integrate generic webgame crawler pipeline"
```

### Task 6: Live multi-platform regression verification

**Files:**
- Create: `tests/live_smoke.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: public URL arguments and the production capture pipeline.
- Produces: a read-only capture summary unless `--download` is supplied.

- [ ] **Step 1: Implement the opt-in live smoke runner**

The runner must accept multiple URLs, print selected frames/engines/hosts/core bytes, reject selected tracking frames, and optionally download. Defaults must avoid turning live URLs into normal unit tests.

- [ ] **Step 2: Run CrazyGames regressions**

Run the Unity, HTML5, and Construct sample URLs. Expected: no DoubleClick selection; Unity includes both `.data.br` and `.wasm.br`; Construct includes `data.json`, WASM, WebP, and WebM.

- [ ] **Step 3: Run Poki regressions**

Run `world-of-yarn` and `water-color-sort`. Expected: a non-tracking game context is selected and cross-domain assets initiated by it are retained.

- [ ] **Step 4: Run Yandex regressions**

Run app IDs `506932` and `481900`. Expected: a non-tracking game context is selected and successful static game assets are accounted for even when the platform uses nested wrappers.

- [ ] **Step 5: Verify Laya coverage**

Run the deterministic Laya fixture. Add a public Laya URL to the live set only after its runtime is positively detected; do not label Laya live-verified without that evidence.

- [ ] **Step 6: Run final verification and commit documentation**

```powershell
py -3.12 -m unittest discover -s tests -v
git diff --check
git add tests/live_smoke.py README.md
git commit -m "test: add multi-platform crawler regressions"
```
