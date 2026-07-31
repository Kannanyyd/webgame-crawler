# HAR Capture and Offline Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve each observed browser session as a full HAR ZIP and prove capture completeness by replaying it with live-network fallback disabled.

**Architecture:** Playwright writes an attached-content HAR during the existing capture session. A small HAR module validates and installs that artifact, while a replay module uses `route_from_har(..., not_found="abort")` in a fresh browser context and classifies unmatched game requests. The current directory downloader remains a secondary compatible output, and the CLI combines both download and replay evidence in its reports and exit status.

**Tech Stack:** Python 3.11+, Playwright synchronous API, standard-library `dataclasses`, `json`, `zipfile`, `tempfile`, and `unittest`.

## Global Constraints

- Keep `python game_grabber.py <url>` compatible.
- Add no required dependency beyond the current `playwright` and `requests` packages.
- Block service workers during HAR capture and replay.
- Never allow replay to fall through to the live network.
- Preserve the existing downloaded-directory output and existing JSON report fields.
- Do not add mitmproxy, Browsertrix, WACZ, engine-parser, or platform-SDK code in this milestone.
- Do not touch or remove the unrelated untracked file `({width`.
- Commit checkpoints locally on the current `main` branch; do not push unless the user requests it.

---

## File Structure

- Create `webgame_crawler/har.py`: inspect a HAR ZIP, verify referenced response attachments, and atomically install the completed archive under `_crawl`.
- Create `webgame_crawler/replay.py`: classify replay failures and perform strict Playwright HAR replay.
- Create `tests/test_har.py`: deterministic standard-library tests for valid and malformed archives.
- Create `tests/test_replay.py`: local-browser integration tests for complete replay, missing required assets, and optional dynamic telemetry.
- Modify `webgame_crawler/models.py`: add HAR and replay result types.
- Modify `webgame_crawler/capture.py`: share bounded page-driving logic, enable HAR recording, block service workers, and close the context explicitly.
- Modify `webgame_crawler/report.py`: serialize HAR and replay evidence.
- Modify `game_grabber.py`: manage the temporary HAR, install it in the final output, run replay, and combine completion status.
- Modify `tests/fixtures/game_site.py`: expose one deterministic telemetry request whose URL changes between capture and replay.
- Modify `tests/test_capture.py`: prove HAR creation and body attachment against the real local fixture.
- Modify `tests/test_cli.py`: prove artifact placement, report fields, and replay-aware exit status through injected deterministic collaborators.
- Modify `README.md`: document the two new `_crawl` artifacts and completeness semantics.

### Task 1: HAR result types and archive validation

**Files:**
- Modify: `webgame_crawler/models.py`
- Create: `webgame_crawler/har.py`
- Create: `tests/test_har.py`

**Interfaces:**
- Produces: `HarArchiveInfo(path: Path, valid: bool, size: int, entry_count: int, body_count: int, error: str | None)`.
- Produces: `ReplayFailure(url: str, method: str, resource_type: str, frame_url: str, error: str, required: bool)`.
- Produces: `ReplaySummary(archive: HarArchiveInfo, requested_url: str, final_url: str, reached_game_surface: bool, failures: list[ReplayFailure], error: str | None)` with `failed`, `required_failed`, and `complete` properties.
- Produces: `inspect_har(path: Path) -> HarArchiveInfo`.
- Produces: `install_har(source: Path, output_dir: Path) -> Path`.

- [ ] **Step 1: Write failing archive-inspection tests**

Create `tests/test_har.py` with a helper that writes a literal HAR ZIP containing `har.har` and `resources/body.bin`. Add tests with these observable expectations:

```python
def test_inspect_har_counts_entries_and_attached_response_bodies(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "capture.har.zip"
        _write_har_zip(path)
        expected_size = path.stat().st_size

        result = inspect_har(path)

    self.assertTrue(result.valid)
    self.assertEqual(result.size, expected_size)
    self.assertEqual(result.entry_count, 1)
    self.assertEqual(result.body_count, 1)
    self.assertIsNone(result.error)

def test_inspect_har_rejects_a_missing_body_attachment(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "capture.har.zip"
        _write_har_zip(path, include_attachment=False)

        result = inspect_har(path)

    self.assertFalse(result.valid)
    self.assertIn("resources/body.bin", result.error)
```

The helper's HAR entry must contain a literal request URL, response status, MIME type, and `content: {"size": 4, "_file": "resources/body.bin"}`. Derive expected counts as literals, not by calling production helpers.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
py -3.12 -m unittest tests.test_har -v
```

Expected: import failure because `webgame_crawler.har` and the new model types do not exist.

- [ ] **Step 3: Add the result dataclasses**

Append the following public shapes to `webgame_crawler/models.py`:

```python
@dataclass(slots=True)
class HarArchiveInfo:
    path: Path
    valid: bool
    size: int = 0
    entry_count: int = 0
    body_count: int = 0
    error: str | None = None


@dataclass(slots=True)
class ReplayFailure:
    url: str
    method: str = "GET"
    resource_type: str = "other"
    frame_url: str = ""
    error: str = "request not found in HAR"
    required: bool = False


@dataclass(slots=True)
class ReplaySummary:
    archive: HarArchiveInfo
    requested_url: str
    final_url: str = ""
    reached_game_surface: bool = False
    failures: list[ReplayFailure] = field(default_factory=list)
    error: str | None = None

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def required_failed(self) -> int:
        return sum(1 for failure in self.failures if failure.required)

    @property
    def complete(self) -> bool:
        return (
            self.archive.valid
            and self.error is None
            and self.reached_game_surface
            and self.required_failed == 0
        )
```

- [ ] **Step 4: Implement minimal HAR validation and installation**

Create `webgame_crawler/har.py` using only `json`, `os`, `zipfile`, and `Path`:

```python
def inspect_har(path: Path) -> HarArchiveInfo:
    # Return a structured invalid result for missing/empty/non-ZIP/malformed files.
    # Locate the single member whose name ends with ".har".
    # Parse log.entries and count entries.
    # Count response.content when it has non-empty inline "text" or a valid "_file".
    # Reject every referenced "_file" absent from the ZIP member-name set.


def install_har(source: Path, output_dir: Path) -> Path:
    destination = output_dir / "_crawl" / "capture.har.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)
    return destination
```

Catch `OSError`, `zipfile.BadZipFile`, `json.JSONDecodeError`, `KeyError`, and `TypeError` in `inspect_har`; preserve the exception text in `error`. A structurally valid archive requires at least one entry and at least one stored response body.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
py -3.12 -m unittest tests.test_har -v
```

Expected: both archive tests pass.

- [ ] **Step 6: Commit the checkpoint**

```powershell
git add webgame_crawler/models.py webgame_crawler/har.py tests/test_har.py
git commit -m "feat: validate captured HAR archives"
```

### Task 2: Record the real browser session as HAR

**Files:**
- Modify: `webgame_crawler/capture.py`
- Modify: `tests/test_capture.py`

**Interfaces:**
- Consumes: `inspect_har(path: Path) -> HarArchiveInfo` from Task 1.
- Produces: `drive_game_page(page: Any, url: str, activity: _NetworkActivity, initial_wait_ms: int, idle_seconds: float, timeout_seconds: float) -> tuple[bool, bool]`, returning `(clicked_start, has_surface)`.
- Changes: `capture_game(..., har_path: str | Path | None = None) -> CaptureResult`.

- [ ] **Step 1: Write a failing real-browser HAR test**

Extend `tests/test_capture.py`:

```python
def test_capture_writes_full_har_with_attached_bodies(self):
    browser_path = Path(__file__).resolve().parents[1] / ".pw-browsers"
    with tempfile.TemporaryDirectory() as temp_dir, GameFixture() as fixture:
        har_path = Path(temp_dir) / "capture.har.zip"
        capture_game(
            fixture.url,
            browser_path=browser_path,
            headless=True,
            initial_wait_ms=250,
            idle_seconds=0.5,
            timeout_seconds=8,
            har_path=har_path,
        )
        archive = inspect_har(har_path)

    self.assertTrue(archive.valid, archive.error)
    self.assertGreater(archive.entry_count, 0)
    self.assertGreater(archive.body_count, 0)
```

This catches removal of HAR options, failure to close the context, and attached-body omission through the resulting artifact rather than inspecting mocked Playwright arguments.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
py -3.12 -m unittest tests.test_capture.CaptureTests.test_capture_writes_full_har_with_attached_bodies -v
```

Expected: `TypeError` because `capture_game` does not accept `har_path`.

- [ ] **Step 3: Extract the existing bounded page-driving sequence**

Move the current navigation, wait, start-control click, game-surface focus, and relevant-idle sequence into `drive_game_page`. Keep its conditions and time budgets unchanged. `capture_game` must call this helper and then continue with the existing frame snapshot and selection code.

- [ ] **Step 4: Add HAR context options and explicit context closure**

Build the context arguments locally in `capture_game`:

```python
context_options = {
    "viewport": {"width": 1280, "height": 800},
    "user_agent": existing_user_agent,
    "service_workers": "block",
}
if har_path is not None:
    har_file = Path(har_path)
    har_file.parent.mkdir(parents=True, exist_ok=True)
    context_options.update(
        record_har_path=str(har_file),
        record_har_content="attach",
        record_har_mode="full",
    )
```

Collect title, URL, cookies, and user agent before closing. Call `context.close()` explicitly to flush HAR, then call `browser.close()` in a `finally` block. Do not read or move the HAR from inside `capture_game`.

- [ ] **Step 5: Run capture tests and verify GREEN**

Run:

```powershell
py -3.12 -m unittest tests.test_capture -v
```

Expected: all capture tests pass and the new test reports a valid archive with attached bodies.

- [ ] **Step 6: Commit the checkpoint**

```powershell
git add webgame_crawler/capture.py tests/test_capture.py
git commit -m "feat: record browser capture as HAR"
```

### Task 3: Strict offline replay and failure classification

**Files:**
- Create: `webgame_crawler/replay.py`
- Create: `tests/test_replay.py`
- Modify: `tests/fixtures/game_site.py`

**Interfaces:**
- Consumes: `drive_game_page` and `_game_surface_urls` from `webgame_crawler.capture`.
- Consumes: `CaptureResult`, `HarArchiveInfo`, `ReplayFailure`, and `ReplaySummary`.
- Produces: `is_required_replay_failure(request: Any, capture: CaptureResult) -> bool`.
- Produces: `verify_replay(har_path: Path, capture: CaptureResult, browser_path: str | Path | None = None, headless: bool = True, timeout_seconds: float = 20.0) -> ReplaySummary`.

- [ ] **Step 1: Add a changing optional telemetry request to the fixture**

In the portal fixture HTML, add:

```html
<script>fetch('/analytics?nonce=' + crypto.randomUUID())</script>
```

Make `PortalHandler.do_GET` return HTTP 204 for paths beginning `/analytics?nonce=`. This guarantees the replay generates a URL absent from the recorded HAR while leaving game loading unaffected.

- [ ] **Step 2: Write failing replay tests**

Create `tests/test_replay.py` with these three behaviors:

```python
def test_complete_har_reaches_the_game_without_required_failures(self):
    # Capture while GameFixture is live, close the fixture servers, then replay.
    self.assertTrue(result.archive.valid, result.archive.error)
    self.assertTrue(result.reached_game_surface)
    self.assertEqual(result.required_failed, 0)

def test_replay_reports_removed_game_asset_as_required(self):
    # Rewrite only har.har in a copied ZIP, removing the entry whose URL is
    # fixture.asset_url while retaining all ZIP attachments.
    self.assertIn(fixture.asset_url, [item.url for item in result.failures])
    self.assertEqual(result.required_failed, 1)
    self.assertFalse(result.complete)

def test_replay_reports_changing_portal_telemetry_as_optional(self):
    telemetry = [item for item in result.failures if "/analytics?nonce=" in item.url]
    self.assertEqual(len(telemetry), 1)
    self.assertFalse(telemetry[0].required)
```

The ZIP-rewrite helper must copy every member verbatim except the parsed HAR JSON and remove exactly one `log.entries` element by literal request URL comparison.

- [ ] **Step 3: Run replay tests and verify RED**

Run:

```powershell
py -3.12 -m unittest tests.test_replay -v
```

Expected: import failure because `webgame_crawler.replay` does not exist.

- [ ] **Step 4: Implement pure required-failure classification**

Classification must return `False` unless the request method is `GET` and its URL is not tracking. It returns `True` when either:

1. the exact URL is present in `capture.selected_resources`; or
2. its frame URL is one of `capture.selected_frames`, and its resource type is `document`, `script`, `stylesheet`, `image`, `media`, or `font`; or
3. its frame URL is selected and `is_game_like_resource(ResourceRecord(url=..., resource_type=...))` is true.

Extensionless `xhr`/`fetch` calls and portal-frame telemetry remain optional unless their exact URL was already selected as a game dependency.

- [ ] **Step 5: Implement strict HAR replay**

`verify_replay` must validate the archive first, configure the same user agent, block service workers, and install strict routing:

```python
archive = inspect_har(har_path)
if not archive.valid:
    return ReplaySummary(
        archive=archive,
        requested_url=capture.requested_url,
        error=archive.error,
    )

context = browser.new_context(
    viewport={"width": 1280, "height": 800},
    user_agent=capture.user_agent or DEFAULT_USER_AGENT,
    service_workers="block",
)
context.route_from_har(str(har_path), not_found="abort")
```

Attach `requestfailed` before navigation. Convert every failure to `ReplayFailure` using the real request URL, method, resource type, frame URL, `request.failure`, and `is_required_replay_failure`. Use `_NetworkActivity` listeners and `drive_game_page` to repeat the bounded interaction. Determine `reached_game_surface` by intersecting current canvas-frame URLs with selected frame URLs; for a selected engine-bearing frame without a canvas, accept an exact selected frame URL that loaded successfully.

Always close context and browser. Convert navigation/browser errors into `ReplaySummary.error` while preserving failures already collected. Do not call `page.route`, `route.fallback`, `route.continue_`, `requests`, or any other network client.

- [ ] **Step 6: Run replay tests and verify GREEN**

Run:

```powershell
py -3.12 -m unittest tests.test_replay -v
```

Expected: all three replay behaviors pass with the fixture servers stopped during replay.

- [ ] **Step 7: Commit the checkpoint**

```powershell
git add webgame_crawler/replay.py tests/test_replay.py tests/fixtures/game_site.py
git commit -m "feat: verify captures with offline HAR replay"
```

### Task 4: CLI orchestration and replay reports

**Files:**
- Modify: `webgame_crawler/report.py`
- Modify: `game_grabber.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Changes: `write_reports(capture, resources, downloads, output_dir, replay: ReplaySummary | None = None) -> dict`.
- Changes: `run(..., replay_func=verify_replay, inspect_har_func=inspect_har) -> int` while preserving existing caller defaults.

- [ ] **Step 1: Write failing report and exit-status tests**

Add a CLI test helper that writes a literal valid HAR ZIP to the `har_path` received by an injected `capture_func`. Inject a replay function returning a `ReplaySummary` with one required `ReplayFailure`. Assert:

```python
self.assertEqual(exit_code, 1)
self.assertTrue((output_dir / "_crawl" / "capture.har.zip").is_file())
self.assertEqual(report["harBytes"], har_size)
self.assertFalse(report["replayComplete"])
self.assertEqual(report["replayFailed"], 1)
self.assertEqual(report["replayRequiredFailed"], 1)
```

Add a second test whose replay summary is complete and whose downloader has only optional failures; assert exit code `0`. Update existing injected capture functions to accept `har_path`, write the literal valid archive, and update injected replay functions to accept `(har_path, capture, **kwargs)`.

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```powershell
py -3.12 -m unittest tests.test_cli -v
```

Expected: failure because `run` does not pass `har_path`, install an archive, call replay, or expose replay report fields.

- [ ] **Step 3: Extend report serialization**

When `replay` is present, write `_crawl/replay-verification.json` with this stable shape:

```python
{
    "archive": str(replay.archive.path),
    "archiveValid": replay.archive.valid,
    "archiveError": replay.archive.error,
    "requestedUrl": replay.requested_url,
    "finalUrl": replay.final_url,
    "reachedGameSurface": replay.reached_game_surface,
    "complete": replay.complete,
    "failed": replay.failed,
    "requiredFailed": replay.required_failed,
    "error": replay.error,
    "failures": [
        {
            "url": failure.url,
            "method": failure.method,
            "type": failure.resource_type,
            "frameUrl": failure.frame_url,
            "error": failure.error,
            "required": failure.required,
        }
        for failure in replay.failures
    ],
}
```

Add `harBytes`, `replayComplete`, `replayFailed`, and `replayRequiredFailed` to `summary.json`. If `replay is None`, use `0`, `None`, `0`, and `0` respectively so existing direct callers remain valid.

- [ ] **Step 4: Orchestrate temporary HAR, installation, and replay**

In `game_grabber.run`:

1. create `output_root` if needed;
2. create a unique sibling file with `tempfile.NamedTemporaryFile(prefix="webgame-", suffix=".har.zip", dir=output_root, delete=False)` and close it before Playwright uses the path;
3. remove that single empty placeholder with `Path.unlink()` before capture;
4. pass `har_path=temp_har` to `capture_func`;
5. after computing `output_dir`, call `install_har(temp_har, output_dir)`;
6. call `replay_func(installed_har, capture, browser_path=PW_BROWSERS_PATH, headless=True)`;
7. pass replay to `write_reports`;
8. return `1` when `downloads.required_failed > 0` or `not replay.complete`;
9. in a `finally` block, unlink only `temp_har` if it still exists.

Use `inspect_har_func` to generate a structured invalid replay result if installation or validation fails; do not silently proceed as complete. Keep the current early return `2` when no game context is selected and ensure the temporary file is still removed.

- [ ] **Step 5: Print concise replay evidence**

Extend terminal output with one line:

```text
Replay complete=<bool> Failed=<count> Required failed=<count> HAR=<MB> MB
```

Do not print every optional failure to the terminal; exact entries belong in `replay-verification.json`.

- [ ] **Step 6: Run CLI tests and verify GREEN**

Run:

```powershell
py -3.12 -m unittest tests.test_cli -v
```

Expected: all CLI tests pass, including archive placement and replay-aware exit status.

- [ ] **Step 7: Commit the checkpoint**

```powershell
git add game_grabber.py webgame_crawler/report.py tests/test_cli.py
git commit -m "feat: report HAR replay completeness"
```

### Task 5: Documentation and full regression verification

**Files:**
- Modify: `README.md`
- Test: all `tests/test_*.py`

**Interfaces:**
- Consumes: final CLI artifacts and JSON field names from Task 4.
- Produces: user-facing documentation of authoritative HAR capture and replay verification.

- [ ] **Step 1: Update output documentation**

Add `_crawl/capture.har.zip` and `_crawl/replay-verification.json` to the README output tree. State that HAR is the faithful browser-session artifact, the normal directory remains a convenience export, replay has no live-network fallback, exact unmatched requests and required status are reported, package size alone does not establish completeness, and server-backed functionality can still require the original platform.

- [ ] **Step 2: Run the complete deterministic test suite**

Run:

```powershell
py -3.12 -m unittest discover -s tests -v
```

Expected: exit code `0` and no failed or errored tests.

- [ ] **Step 3: Run static and repository checks**

Run:

```powershell
py -3.12 -m compileall -q game_grabber.py webgame_crawler tests
git diff --check
git status --short
```

Expected: both commands exit `0`; status lists only the milestone changes plus the preserved unrelated `?? ({width`.

- [ ] **Step 4: Run one opt-in local end-to-end crawl**

Use `GameFixture` from a short Python command to call `game_grabber.run` against the local portal with a temporary output directory. Assert the command returns `0`, then inspect that both `_crawl/capture.har.zip` and `_crawl/replay-verification.json` exist. This check must not contact an external website.

- [ ] **Step 5: Review acceptance criteria against fresh evidence**

Confirm from the preceding commands that existing tests stayed green, the real browser generated an attached-body HAR, replay completed after fixture servers stopped, a deliberately removed core asset was required and incomplete, changing portal telemetry was optional, CLI output and JSON fields remained backward-compatible, and no new dependency was added.

- [ ] **Step 6: Commit the final checkpoint**

```powershell
git add README.md
git commit -m "docs: explain HAR replay verification"
```

- [ ] **Step 7: Show the final local history without pushing**

```powershell
git log --oneline -6
git status --short
```

Expected: the HAR implementation checkpoints are present locally, and `?? ({width` remains unmodified and uncommitted.
