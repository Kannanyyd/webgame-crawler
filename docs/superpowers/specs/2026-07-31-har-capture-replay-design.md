# HAR Capture and Offline Replay Design

**Status:** Approved direction, written for user review

**Date:** 2026-07-31

## Purpose

Make browser capture the authoritative source of truth for resources needed to reach the observed game screen. The crawler will preserve a complete Playwright HAR archive and verify it by replaying without network fallback, while retaining the current downloaded-directory output for compatibility.

This is the first integration milestone. It deliberately does not add mitmproxy, Browsertrix, cc-reverse, UnityPy, or platform-SDK shims yet. Those components remain later fallbacks or engine plugins after the capture layer has a deterministic completeness check.

## Confirmed Problem

The current pipeline records browser request metadata and then downloads selected URLs again with `requests`. That second transfer is not equivalent to the browser transfer:

- response bodies can be compressed while the local directory does not preserve the response headers needed to interpret them;
- redirects, document responses, cookies, signed queries, and platform SDK requests can differ between browser capture and later downloading;
- a successful download count or package size does not prove that the saved set can reproduce the observed loading path;
- engine resources loaded only after a later runtime event can remain undiscovered.

The crawler needs both a faithful browser-session artifact and a replay test that exposes every request the artifact cannot satisfy.

## Goals

1. Record a full Playwright HAR ZIP, including response content, for every crawl.
2. Disable service workers during capture and replay so requests cannot bypass HAR accounting.
3. Close the browser context cleanly before consuming the HAR, because Playwright flushes HAR data on context close.
4. Replay the captured navigation with HAR routing and no network fallback.
5. Record every replay request failure, including URL, method, resource type, frame URL, and failure reason.
6. Distinguish missing game dependencies from optional portal, advertising, analytics, and backend requests.
7. Preserve the existing command and downloaded-directory reports.
8. Return a non-zero incomplete result only when replay misses a required game dependency or the existing downloader misses a required resource.

## Non-Goals

1. Making online services such as multiplayer, payments, leaderboards, or advertisements work offline.
2. Replacing the existing downloader with a complete HAR-to-directory exporter in this milestone.
3. Bypassing login, CAPTCHA, DRM, authorization, or platform access controls.
4. Adding engine-specific recursive parsers in the same change.
5. Treating every portal analytics failure as a failed game capture.

## Considered Approaches

### A. Playwright HAR as the default capture artifact

This is the selected approach. It uses the project's existing browser dependency, observes the same browser session used for game discovery, stores response content, and supports deterministic replay through `route_from_har(..., not_found="abort")`.

Trade-off: HAR does not provide a directly browsable local directory, and service-worker traffic must be blocked to keep replay accounting reliable.

### B. mitmproxy as the default capture layer

mitmproxy can retain precise request and response semantics and is a strong fallback for difficult sites. Making it the default now would add certificate setup, proxy lifecycle management, QUIC handling, and another required process before the existing pipeline has a replay oracle.

### C. Browsertrix/WACZ as the default capture layer

Browsertrix provides high-fidelity behavior-driven capture and WACZ replay, but requires Docker and has AGPL integration constraints. It is better kept as an optional external backend after the local CLI defines a stable capture-backend interface.

## Architecture

The change introduces two focused modules and small orchestration changes:

- `webgame_crawler/har.py`: defines HAR paths, validates that an archive exists and contains response bodies, and moves the completed temporary archive into the output report directory.
- `webgame_crawler/replay.py`: opens a fresh Playwright context, routes all requests from HAR with network fallback disabled, observes failed/unmatched requests, and classifies whether each failure belongs to a selected game context.
- `webgame_crawler/capture.py`: accepts a HAR output path, creates the browser context with full attached HAR content and blocked service workers, and explicitly closes the context before the browser.
- `webgame_crawler/models.py`: adds typed replay records and a replay summary.
- `webgame_crawler/report.py`: writes `_crawl/replay-verification.json` and includes replay counts in `summary.json`.
- `game_grabber.py`: creates a temporary HAR location, runs capture, moves the HAR to `<game>/_crawl/capture.har.zip`, runs strict replay, writes reports, and combines downloader and replay completeness into the exit status.

No generic plugin framework is added yet. A capture-backend abstraction will only be introduced when a second backend, such as mitmproxy, is actually implemented.

## Capture Data Flow

1. The CLI creates a unique temporary HAR path under the selected output root.
2. `capture_game` creates a browser context with:
   - `record_har_path` set to the temporary `.har.zip` path;
   - `record_har_content="attach"`;
   - `record_har_mode="full"`;
   - `service_workers="block"`.
3. Existing navigation, start-control interaction, frame discovery, and resource selection run unchanged.
4. Browser state needed by the existing downloader is collected.
5. The context is closed, flushing the HAR, and then the browser is closed.
6. After the game title determines the output directory, the archive is moved to `_crawl/capture.har.zip`.
7. HAR validation rejects a missing, empty, malformed, or body-less archive with a structured failure.

Temporary files are removed individually on handled failures. Existing user output is never recursively deleted.

## Offline Replay

Replay uses a new browser context with service workers blocked. The context installs HAR routing with `not_found="abort"`, navigates to the original requested URL, and repeats the same bounded generic interaction used during capture.

The interaction helper will be shared from `capture.py`; the discovery algorithm itself is not duplicated. Replay stops using the same relevant-network idle and maximum-time conditions as capture.

For every failed request, replay records:

- exact URL and method;
- resource type;
- current frame URL and ancestors when available;
- Playwright failure text;
- whether it matches a URL captured as a selected game resource;
- whether its frame is a selected game frame or descendant;
- `required`, which is true only for game-context documents and static game dependencies.

Optional portal telemetry, advertisements, and server APIs remain visible in the report but do not fail the crawl.

## Completeness Rules

Replay is complete when all of these hold:

1. the requested document is fulfilled from HAR;
2. at least one previously selected game context is reached;
3. no required game-context request is unmatched;
4. the replay reaches a canvas or the same engine-bearing game frame observed during capture;
5. the HAR itself passes structural validation.

The crawl exit status is incomplete when either the existing downloader has `required_failed > 0` or replay has required failures. This keeps current behavior while adding a stronger independent check.

Package size is reported as evidence only; it is never used as a completeness criterion.

## Reports and Artifacts

Each successful capture attempt produces:

```text
<game-name>/
  ...existing downloaded resources...
  _crawl/
    capture.har.zip
    resource-map.json
    summary.json
    failures.json
    replay-verification.json
```

`replay-verification.json` contains:

- archive path and validation result;
- replay start and final URLs;
- whether a game surface was reached;
- total and required failure counts;
- one structured entry per failed request;
- a concise terminal-facing failure reason when replay cannot start.

`summary.json` adds `harBytes`, `replayComplete`, `replayFailed`, and `replayRequiredFailed` without removing existing fields.

## Error Handling

- HAR creation, validation, and replay errors become report data rather than unhandled tracebacks.
- A capture that cannot produce a valid HAR is incomplete even if the secondary downloader succeeds.
- Replay timeouts preserve all failures collected before timeout.
- Unsupported or dynamic backend requests are labeled optional unless they are required to load the selected game frame or a captured static dependency.
- The implementation will not silently retry against the live network during replay.

## Testing Strategy

Deterministic tests will extend the existing local fixture server:

1. A fixture response with compressed content and response headers appears in the HAR archive.
2. A complete HAR replays the fixture game without live-network access.
3. Removing one required fixture response from a test HAR produces one required replay failure.
4. An unmatched analytics request is reported but remains optional.
5. Service workers are blocked in both capture and replay contexts.
6. Context closure produces a non-empty HAR before validation begins.
7. CLI reports preserve existing fields and add replay fields.
8. Existing dependency injection in CLI tests remains usable without launching a browser.

Live URLs remain opt-in regression checks. They validate capture behavior but are not required for the deterministic unit-test suite.

## Acceptance Criteria

1. Existing deterministic tests continue to pass.
2. New HAR and replay tests pass without contacting an external website.
3. A normal crawl writes a non-empty `_crawl/capture.har.zip`.
4. Replay never falls through to the live network.
5. Missing required game resources are listed with exact URLs and cause a non-zero result.
6. Optional portal/backend failures remain visible without falsely marking the static game capture incomplete.
7. The existing `python game_grabber.py <url>` command remains compatible.
8. No mitmproxy, Docker, Node.js, or engine-parser dependency is required for this milestone.

## Later Integration Boundary

After this milestone provides a reliable replay oracle:

1. add mitmproxy as an optional high-fidelity backend only for HAR-incomplete sites;
2. add Cocos, Unity, and Laya parsers as independent supplemental-discovery plugins;
3. require every plugin-added resource to pass the same offline replay verification;
4. optionally export WACZ for Browsertrix/ReplayWeb.page without copying AGPL source into this repository.
