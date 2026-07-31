# HAR Capture/Replay Final Fix Report

**Date:** 2026-08-01

**Branch:** `main`

**Reviewed baseline:** `ed215aeb421c46f1a156978a4ad32b38d217c97f`

**Implementation commit:** `4f43aef` (`fix: harden offline HAR replay verification`)

**Push status:** not pushed

**Overall status:** DONE

## Scope and constraints

This wave fixes only the two Critical, two Important, and two Minor findings from the final review. The unrelated untracked path `({width` was not read, edited, staged, or committed. No dependency was added and `requirements.txt` remains unchanged.

## CRITICAL 1 — Replay ended before delayed required requests

### Root cause

`verify_replay` drove the page with hard-coded `initial_wait_ms=250` and `idle_seconds=0.5`, and its public timeout default was 20 seconds. Capture used 2 seconds, 4 seconds, and 45 seconds by default. A page that already exposed a canvas and had no start-control click could therefore be declared idle by replay before a delayed required request was emitted.

### RED

Command:

```powershell
py -3.12 -m unittest tests.test_replay.ReplayTests.test_missing_required_request_delayed_after_existing_canvas_is_incomplete -v
```

Evidence against `ed215ae` behavior:

```text
FAIL
AssertionError: 'http://127.0.0.1:52685/late.bundle' not found in []
Ran 1 test in 8.931s
```

The fixture exposed a canvas immediately, emitted `late.bundle` after 1.2 seconds, captured that request with the capture defaults, removed exactly that HAR entry, and showed that the old replay incorrectly collected no failure.

### Change

- Added shared capture defaults in `webgame_crawler.capture`.
- Persisted the actual `initial_wait_ms`, `idle_seconds`, and `timeout_seconds` used by `capture_game` on `CaptureResult`.
- Made `verify_replay` use those captured observation settings unless the caller explicitly overrides them.

### GREEN

Same command:

```text
ok
Ran 1 test in 14.081s
```

The replay now waits long enough to emit the removed request, records it as required, and returns incomplete.

### Commit

`4f43aef`

## CRITICAL 2 — WebSocket and browser networking bypassed HAR routing

### Root cause

`route_from_har(..., not_found="abort")` governs routed HTTP requests but did not isolate WebSocket, WebRTC, WebTransport, or other browser network stacks. The replay context was online, so page script could establish real sockets even though HTTP HAR misses were aborted.

### Browser compatibility investigation

Installed Playwright: `1.61.0`. An exploratory real-browser probe created a full attached HAR, then replayed it in a context constructed with `offline=True` and `route_from_har`:

```text
capture: tcp=2, udp=3
offline replay: tcp=0, udp=0
canvas=1
HAR bytes=1837
```

This established that context-level offline mode is compatible with HAR fulfillment and blocks both a WebSocket TCP attempt and WebRTC STUN UDP. Playwright documents context offline mode as present before v1.9, so the existing `playwright>=1.40.0` lower bound already covers the selected API. `route_web_socket` was therefore unnecessary and the dependency lower bound did not change.

### RED

Command:

```powershell
py -3.12 -m unittest tests.test_replay.ReplayTests.test_har_http_replays_without_live_tcp_or_webrtc_udp_connections -v
```

Evidence against the online replay context:

```text
FAIL
AssertionError: 1 != 0
Ran 1 test in 5.066s
```

The committed regression uses real local TCP accept counting and a real UDP datagram receiver. Capture proves the probes are active (at least two TCP connections and at least one WebRTC UDP datagram), resets the counters, keeps the servers live during replay, and requires HAR HTTP to reach the canvas with zero live TCP/UDP traffic.

### Change

The replay `BrowserContext` is created with `offline=True` before any page is created or script runs. HAR routing still fulfills matching HTTP entries; every browser networking side path is isolated by the context rather than by page JavaScript monkeypatching.

### GREEN

Same command after the fix and strengthened probe assertion:

```text
ok
Ran 1 test in 5.565s
```

### Commit

`4f43aef`

## IMPORTANT 1 — Required classification ignored selected ancestors

### Root cause

Capture already recorded a request frame's ancestor chain, but replay only compared `request.frame.url` with selected frame URLs. A new static URL requested by a nested child of a selected game frame was consequently classified optional.

### RED

Nested real-browser classification command:

```powershell
py -3.12 -m unittest tests.test_replay.ReplayTests.test_new_static_request_in_nested_frame_is_required_via_selected_ancestor -v
```

Evidence:

```text
FAIL
AssertionError: False is not true
Ran 1 test in 4.038s
```

The selected frame contains a canvas and a nested child frame. The child creates a script URL with a new UUID on every load, so replay cannot satisfy the exact URL from HAR. The child itself is deliberately not selected; its selected ancestor must make the new static request required.

Replay JSON RED command:

```powershell
py -3.12 -m unittest tests.test_cli.CliTests.test_run_writes_audit_report_and_returns_incomplete_exit_code -v
```

Evidence:

```text
ERROR
TypeError: ReplayFailure.__init__() got an unexpected keyword argument 'frame_ancestors'
Ran 1 test in 0.025s
```

### Change

- Reused capture's complete request-frame extraction in replay.
- Classified a request in game context when its current frame or any ancestor is selected.
- Added `frame_ancestors` to `ReplayFailure` without changing the prior positional field order.
- Serialized it as `frameAncestors` in `replay-verification.json`.

### GREEN

Command:

```powershell
py -3.12 -m unittest tests.test_replay.ReplayTests.test_new_static_request_in_nested_frame_is_required_via_selected_ancestor tests.test_cli.CliTests.test_run_writes_audit_report_and_returns_incomplete_exit_code -v
```

Evidence:

```text
Ran 2 tests in 4.070s
OK
```

### Commit

`4f43aef`

## IMPORTANT 2 — CLI collaborators were frozen in function defaults

### Root cause

`run` bound capture/download/replay/inspect functions when the function was defined. Patching the current `game_grabber` module later had no effect. The identity check against the current `capture_game` global could then skip `ensure_browser` while the stale original capture function was still invoked.

### RED

Command:

```powershell
py -3.12 -m unittest tests.test_cli.CliTests.test_run_resolves_default_collaborators_at_call_time_and_ensures_browser -v
```

Evidence:

```text
FAIL
AssertionError: stale capture default used
Ran 1 test in 0.066s
```

The test patches all four current module collaborators and places a guard on the stale real Playwright path. The old function ignored the patched capture collaborator.

### Change

- Changed all four collaborator defaults to `None`.
- Recorded `using_default_capture` before resolution.
- Resolved each current module function inside `run`.
- Used the independent flag to run `ensure_browser` for default capture even when the current module function is patched.

### GREEN

Same command:

```text
ok
Ran 1 test in 0.079s
```

Observed order: `ensure`, `capture`, `inspect`, `replay`, `download`.

### Commit

`4f43aef`

## MINOR 1 — Real HAR/replay tests lacked strong artifact assertions

### Coverage gap

This finding did not identify broken production behavior; it identified assertions that were too weak. A genuine RED against the current implementation would have required manufacturing a production regression, so the change was handled as a coverage/mutation guard rather than altering already-correct behavior.

### Change

- The full HAR browser test now opens the ZIP, requires a response `content._file`, reads and compares the attachment bytes, verifies status/MIME type, checks `Content-Type`, `Content-Length`, and `Access-Control-Allow-Origin`, and checks full-mode timing data.
- The complete real replay test now explicitly requires `result.complete` and `result.error is None`.

The strengthened assertions would fail if attached content were changed to embed/omit, if the body attachment were missing/corrupt, if critical response metadata were dropped, if full-mode timing data were omitted, or if replay returned a latent error.

### Verification

Command:

```powershell
py -3.12 -m unittest tests.test_capture.CaptureTests.test_capture_writes_full_har_with_attached_bodies tests.test_replay.ReplayTests.test_complete_har_reaches_the_game_without_required_failures -v
```

Evidence:

```text
Ran 2 tests in 11.988s
OK
```

### Commit

`4f43aef`

## MINOR 2 — README described only downloader failure semantics

### Documentation gap

The README said the command failed only when core downloads failed, despite the implemented exit condition also treating incomplete replay as failure.

Per the test-quality rules, human-facing prose was not given a source-text assertion. The change was verified by reviewing the rendered diff and by the existing/new CLI exit-status tests.

### Change

The README now states that either a required resource download failure or incomplete replay makes the command return failure.

### Commit

`4f43aef`

## Final verification

Focused regression suite:

```powershell
py -3.12 -m unittest tests.test_capture tests.test_replay tests.test_cli -v
```

```text
Ran 21 tests in 61.308s
OK
```

Complete deterministic suite:

```powershell
py -3.12 -m unittest discover -s tests -v
```

```text
Ran 58 tests in 62.666s
OK
```

Compilation:

```powershell
py -3.12 -m compileall -q game_grabber.py webgame_crawler tests
```

Result: exit code 0, no output.

Repository whitespace check:

```powershell
git diff --check
```

Result: exit code 0. Git emitted only the repository's existing LF-to-CRLF conversion warnings while inspecting the unstaged files; no whitespace error was reported.

## Remaining concerns

No known in-scope correctness concern remains. The network-isolation regression runs against the project's supported Playwright Chromium path and proves HAR HTTP fulfillment together with zero live WebSocket TCP and WebRTC UDP traffic. The unrelated `({width` path remains untracked and untouched. No push was performed.
