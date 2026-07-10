# Generic Web Game Resource Discovery Design

**Status:** Approved direction, written for user review

**Date:** 2026-07-11

## Purpose

Redesign `webgame-crawler` so a user only needs to provide a public URL that can load into a playable web-game screen. The crawler must discover the real game execution context and the static resource chain without relying on a specific portal domain.

CrazyGames is a regression source, not a special-case architecture. The first engine coverage set is Unity WebGL, Construct, Cocos Creator, LayaAir, and generic HTML5 games.

## Confirmed Problem

The current crawler chooses one iframe first and then keeps only resources sharing that iframe's root domain. This creates a cascading failure:

1. A portal page contains game, analytics, consent, and advertising frames.
2. The current heuristic searches the entire frame URL, including its query string, for words such as `games.`.
3. A DoubleClick URL containing `crazygames.com` in a query parameter is selected as the game frame.
4. Engine detection runs against the advertising frame and returns `unknown`.
5. Root-domain filtering discards the real game resources.

This reproduced on all three live samples:

| Sample | Engine | Browser requests | Resources after current filtering | Saved size |
|---|---|---:|---:|---:|
| Arrow Exit Puzzle | Unity 6 | 442 | 12 | 0.77 MB |
| Arrow Escape Puzzle | HTML5 | 494 | 11 | 0.77 MB |
| Crazy City Multiplayer | Construct | 675 | 11 | 0.77 MB |

The Unity sample's two core Brotli assets total about 28.3 MB compressed and 69.7 MB uncompressed. They were visible to the browser but removed before download.

## Goals

1. Discover the game context from browser behavior, not from a portal-specific hostname list.
2. Preserve every successful static GET resource required to reach the observed playable screen, including resources on unrelated CDN domains.
3. Preserve full URLs, query strings, redirects, request context, response headers, compressed bytes, and provenance.
4. Use engine manifests to discover lazy resources that were not loaded during the observation window.
5. Produce an auditable report explaining why each captured request was included, excluded, failed, or deduplicated.
6. Keep the existing CLI entry point: `python game_grabber.py <url>`.
7. Support Windows terminals without requiring the caller to change console encoding manually.

## Non-Goals

1. Bypassing login, payment, CAPTCHA, DRM, or access controls.
2. Guaranteeing offline multiplayer, leaderboards, advertisements, payments, or other server-backed APIs.
3. Downloading every level or optional asset that the game never requests and does not expose through a manifest.
4. Maintaining per-portal hardcoded allowlists as the primary discovery mechanism.

For static games, local replay should reach the same initial playable screen observed during capture. Dynamic online functionality may still require its original backend.

## Design Principle

The crawler will build a resource graph and select game-related request clusters. It will not select one frame and assume that all valid resources share its root domain.

The graph records:

- document and iframe navigation;
- parent and child frame relationships;
- requests made by each frame;
- redirects;
- response type, status, headers, encoded size, and decoded-size metadata;
- request initiators when available through Chromium DevTools Protocol;
- manifest-to-resource relationships discovered after browser capture.

This allows a game document on one host to legitimately load scripts, textures, audio, WASM, and data from several unrelated CDNs.

## Architecture

The existing command remains the orchestrator, while focused modules separate capture, classification, manifest discovery, and storage:

- `game_grabber.py`: CLI parsing, progress output, orchestration, and exit status.
- `webgame_crawler/models.py`: typed records for frames, requests, responses, resource decisions, and crawl summaries.
- `webgame_crawler/capture.py`: Playwright/CDP browser lifecycle, navigation, interaction, and network event collection.
- `webgame_crawler/discovery.py`: game-context scoring, resource-graph traversal, classification, and readiness detection.
- `webgame_crawler/manifests.py`: engine detection and manifest-based supplemental discovery.
- `webgame_crawler/download.py`: authenticated downloading, exact-byte storage, validation, retries, and URL-to-file mapping.
- `webgame_crawler/report.py`: machine-readable JSON report plus concise terminal summary.

This is a targeted split of the current 818-line script. Engine support remains in one manifest module until the implementations become large enough to justify separate plugins.

## Browser Capture

Network listeners are attached before navigation. Playwright provides frames and browser-context state; a Chromium DevTools Protocol session provides request IDs, initiator information, encoded transfer lengths, and loading completion events.

For every request, capture:

- exact URL, including query and fragment handling;
- method and resource type;
- originating frame and frame ancestry;
- redirect ancestry;
- original request headers needed for a safe GET replay;
- response status and headers;
- encoded transfer length when available;
- `Content-Length`, `Content-Encoding`, and uncompressed-length metadata;
- completion or failure reason.

Document requests are retained. They are needed to identify the entry document and make local replay possible.

## Game-Context Discovery

Frame and request clusters receive evidence scores after the initial page settles. No score uses a frame's query string as a hostname signal.

Positive evidence includes:

- a visible canvas or WebGL context;
- known engine globals or script names;
- a large amount of image, audio, video, font, WASM, or binary traffic;
- a document that initiates data/asset requests and continues network activity after the portal shell is idle;
- a child frame whose descendants contain the preceding signals;
- a loading screen or progress element followed by stable canvas activity.

Negative evidence includes:

- known advertising, analytics, consent, and tracking hostnames evaluated from parsed hostnames only;
- frames containing only pixels, auctions, user-sync calls, or tiny tracking responses;
- no canvas, no engine signals, and no meaningful asset bytes;
- frames whose only game-related text appears inside query parameters.

The result is a set of plausible game contexts, not necessarily one frame. If confidence is low, the crawler keeps the union of plausible game clusters and reports low confidence rather than falling back to the first iframe.

## Resource Inclusion

A resource is included when at least one of these conditions holds:

1. It was requested by a selected game frame or one of its descendants.
2. Its initiator chain leads to a selected game request, even when its hostname is unrelated.
3. It is referenced by an included HTML, CSS, JavaScript, or JSON resource.
4. It is discovered through a validated engine manifest.
5. It is a redirect target of an included request.

Advertising and tracking requests are excluded by explicit classification, not by requiring a shared root domain. Unknown cross-origin resources initiated by the game are retained by default and labeled `unknown-game-dependency`.

Every exclusion is recorded with a reason. This makes false positives and false negatives diagnosable without adding temporary logging to production code.

## Interaction and Completion

The user only supplies a URL. The crawler performs bounded generic interaction:

1. Load the portal document.
2. Click one visible start control whose accessible name matches a conservative play/run/start vocabulary.
3. Observe newly attached and navigated frames.
4. Focus and click the center of the strongest canvas candidate once when needed.
5. Wait for a condition-based settling window.

Capture completes when all of the following are true:

- at least one plausible game context exists;
- relevant in-flight requests are zero;
- no new relevant resource URL or bytes have appeared for a settling interval;
- engine-specific readiness, when available, reports a running scene or completed loader.

A maximum timeout prevents endless waits. Fixed sleeps remain only as small polling intervals, not as the definition of completion.

## URL and Session Fidelity

Full URLs are immutable discovery keys. Query parameters are never discarded. Local filename collisions caused by query variants are resolved with a stable short hash, while the report retains the original URL.

Downloads reuse browser state:

- cookies are copied from the Playwright context;
- the browser user agent and safe captured headers are preserved;
- referer and origin are derived from the actual request, not guessed globally;
- authorization and custom headers are retained when present;
- `200` and valid `206` responses are supported;
- redirects remain enabled and are recorded;
- content is streamed to disk rather than buffered entirely in memory.

For encoded assets such as `.br` and `.gz`, the downloader stores raw encoded bytes and records decoded-size metadata separately. It validates response length when the server provides a reliable length and removes incomplete temporary files after failed attempts.

## Relative URL Resolution

Every relative URL is resolved against the URL of the document, stylesheet, script, or manifest that contains it. It is never resolved against `game_frame_url + "/"`.

For example:

```text
Source:   https://cdn.example/game/index.html
Relative: Build/game.data
Result:   https://cdn.example/game/Build/game.data
```

The same rule applies to URLs extracted from JavaScript, CSS, JSON, Unity loader configuration, Construct data, Cocos bundle configuration, and Laya manifests.

## Engine Supplementation

Network capture is authoritative. Engine logic supplements it with lazy resources.

### Unity WebGL

- Detect Unity globals, loader scripts, loader configuration, and common Build assets.
- Resolve `dataUrl`, `frameworkUrl`, `codeUrl`, `streamingAssetsUrl`, loader URLs, and symbols relative to their source document or script.
- Include `.data`, `.wasm`, `.framework.js`, `.symbols.json`, `.unityweb`, `.br`, and `.gz` variants.

### Construct

- Detect `c3runtime`, `c3main`, preview/runtime scripts, and `data.json`.
- Traverse asset references in `data.json` and related runtime manifests.
- Include WebP, WebM, WASM, audio, video, fonts, JSON, and worker scripts.

### Cocos Creator

- Detect Cocos globals and boot/application scripts.
- Read settings and bundle configuration variants.
- Follow bundle, import, native, pack, UUID, and version mappings rather than synthesizing only one assumed URL shape.

### LayaAir

- Detect `Laya`, `Laya3D`, Laya runtime scripts, and boot configuration.
- Parse available version, file, atlas, scene, and resource configuration.
- Include common Laya resources such as `.atlas`, `.json`, `.lh`, `.ls`, `.lm`, `.lmat`, `.lav`, `.ani`, `.sk`, `.scene`, `.prefab`, textures, audio, video, fonts, and binary files.

### Generic HTML5

- Parse included HTML, CSS, JavaScript, and JSON for static resource references.
- Cover image, audio, video, font, model, texture, compressed, WASM, data, and binary extensions, including `.webm`, `.mp4`, `.ktx2`, `.basis`, `.dds`, `.pck`, `.br`, and `.gz`.
- Use the source resource URL as the resolution base.

## Storage and Reporting

The output keeps URL paths recognizable while separating unrelated hosts:

```text
<game-name>/
  index.html
  _external/<host>/...
  _crawl/resource-map.json
  _crawl/summary.json
  _crawl/failures.json
```

`resource-map.json` maps every original URL to its local path, source context, initiator, status, headers, byte counts, classification, and discovery method.

The terminal summary reports:

- total browser requests;
- plausible game contexts and confidence;
- included, excluded, downloaded, skipped, and failed counts;
- encoded bytes saved and known decoded bytes;
- totals grouped by host, type, and discovery method;
- the largest missing or failed resources.

An existing non-empty file is only skipped when its recorded URL identity and expected validation data still match. A non-empty error page is not considered a valid cached resource.

## Error Handling

- Replace silent broad exception handling on critical paths with structured diagnostic records.
- Continue after individual optional-resource failures, but return a non-zero incomplete result when required entry or core engine resources fail.
- Distinguish navigation, classification, authentication, HTTP, timeout, length mismatch, decode, and filesystem failures.
- Print Unicode safely on Windows or fall back to ASCII markers.
- Validate that the installed Playwright package has its expected browser revision instead of accepting any `chromium-*` directory.

## Testing Strategy

### Deterministic Unit and Integration Tests

Create local fixture sites covering:

1. A real game iframe plus an advertising iframe whose query contains `crazygames.com`.
2. Game assets on an unrelated CDN hostname.
3. Two resources with the same path and different signed query strings.
4. Cookie-protected and custom-header-protected assets.
5. A valid `206 Partial Content` response.
6. Brotli metadata and encoded-byte preservation.
7. Lazy resources referenced only by Unity, Construct, Cocos, and Laya manifests.
8. Generic HTML5 WebM and modern texture formats.
9. Correct relative resolution from `index.html`, nested scripts, and nested manifests.
10. Incomplete files and HTTP-200 HTML error bodies not being treated as valid cached assets.

### Live Opt-In Regression Tests

Live portal tests are opt-in because URLs and assets can change:

- Unity: `https://www.crazygames.com/game/arrow-exit-puzzle`
- HTML5: `https://www.crazygames.com/game/arrow-escape-puzzle`
- Construct: `https://www.crazygames.com/game/crazy-city-multiplayer`
- LayaAir: add one confirmed public sample before declaring Laya live coverage complete.

For every live test:

- no advertising frame may be selected as the game context;
- known core game resource URLs must be included;
- filtering must not reduce the game cluster to tracking hosts;
- the crawl report must account for every captured core resource;
- local output must contain the entry document and required initial-screen assets.

## Acceptance Criteria

The redesign is accepted when:

1. All deterministic tests pass.
2. The three confirmed CrazyGames samples identify real game contexts and no longer select DoubleClick.
3. The Unity sample queues both core Brotli assets and reports encoded and decoded sizes separately.
4. The Construct sample queues `data.json`, WASM, WebP, and WebM resources.
5. A Laya fixture passes, and a live Laya URL passes before Laya support is advertised as live-verified.
6. Cross-domain, signed-query, cookie, and 206 fixtures download successfully.
7. The CLI remains compatible with `python game_grabber.py <url>`.
8. Failures are visible in reports; no critical discovery or download exception is silently discarded.
