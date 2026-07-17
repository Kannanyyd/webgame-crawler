from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from .models import DownloadResult, DownloadSummary, ResourceRecord


UNSAFE_HEADER_NAMES = {
    "host",
    "content-length",
    "cookie",
    "range",
    "connection",
    "proxy-connection",
    "transfer-encoding",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
}


def _safe_segment(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return value or "_"


def resource_local_path(url: str, main_host: str) -> Path:
    parsed = urlparse(url)
    decoded_path = unquote(parsed.path)
    segments = [_safe_segment(segment) for segment in decoded_path.split("/") if segment]
    if not segments or decoded_path.endswith("/"):
        segments.append("index.html")

    filename = Path(segments[-1])
    if parsed.query:
        query_hash = hashlib.sha256(parsed.query.encode("utf-8")).hexdigest()[:10]
        if filename.suffix:
            filename = filename.with_name(f"{filename.stem}__q{query_hash}{filename.suffix}")
        else:
            filename = filename.with_name(f"{filename.name}__q{query_hash}.bin")
        segments[-1] = filename.name
    elif not filename.suffix:
        segments[-1] = filename.name + ".bin"

    relative = Path(*segments)
    if parsed.netloc != main_host:
        relative = Path("_external") / _safe_segment(parsed.netloc) / relative
    return relative


def build_session(cookies: list[dict], user_agent: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "*/*",
            "User-Agent": user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
        }
    )
    for cookie in cookies:
        kwargs = {"path": cookie.get("path", "/")}
        domain = cookie.get("domain")
        if domain:
            kwargs["domain"] = domain.lstrip(".")
        session.cookies.set(cookie["name"], cookie["value"], **kwargs)
    return session


def replay_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in UNSAFE_HEADER_NAMES and not name.lower().startswith("sec-ch-")
    }


def fetch_text(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    max_bytes: int = 5 * 1024 * 1024,
) -> str | None:
    try:
        response = session.get(url, headers=replay_headers(headers), timeout=30)
        if response.status_code not in (200, 206):
            return None
        declared = int(response.headers.get("content-length", "0") or 0)
        if declared > max_bytes or len(response.content) > max_bytes:
            return None
        return response.text
    except (requests.RequestException, ValueError):
        return None


def probe_resource_urls(
    session: requests.Session,
    urls: set[str],
    headers: dict[str, str],
    max_workers: int = 16,
) -> set[str]:
    if not urls:
        return set()
    thread_state = threading.local()

    def session_for_thread() -> requests.Session:
        if not hasattr(thread_state, "session"):
            worker = requests.Session()
            worker.headers.update(session.headers)
            worker.cookies.update(session.cookies)
            thread_state.session = worker
        return thread_state.session

    def exists(url: str) -> str | None:
        for attempt in range(2):
            try:
                worker = session_for_thread()
                response = worker.head(
                    url,
                    headers=replay_headers(headers),
                    timeout=15,
                    allow_redirects=True,
                )
                if (
                    response.status_code not in (200, 206, 304)
                    and response.status_code not in (404, 410)
                ):
                    response.close()
                    fallback_headers = replay_headers(headers)
                    fallback_headers["Range"] = "bytes=0-0"
                    response = worker.get(
                        url,
                        headers=fallback_headers,
                        timeout=15,
                        allow_redirects=True,
                        stream=True,
                    )
                status = response.status_code
                response.close()
                if status in (200, 206, 304):
                    return url
                if status != 429 and status < 500:
                    return None
            except requests.RequestException:
                if attempt == 1:
                    return None
            time.sleep(0.1 * (attempt + 1))
        return None

    existing: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = [executor.submit(exists, url) for url in urls]
        for future in as_completed(futures):
            url = future.result()
            if url is not None:
                existing.add(url)
    return existing


def _complete_partial_response(response: requests.Response, bytes_written: int) -> bool:
    if response.status_code != 206:
        return True
    content_range = response.headers.get("content-range", "")
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range.strip(), re.IGNORECASE)
    if not match:
        return False
    start, end, total = (int(value) for value in match.groups())
    return start == 0 and end + 1 == total and bytes_written == total


def download_resources(
    resources: list[ResourceRecord],
    cookies: list[dict],
    output_dir: Path,
    main_host: str,
    user_agent: str = "",
    max_workers: int = 8,
) -> DownloadSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    thread_state = threading.local()

    def session_for_thread() -> requests.Session:
        if not hasattr(thread_state, "session"):
            thread_state.session = build_session(cookies, user_agent)
        return thread_state.session

    def download_one(resource: ResourceRecord) -> DownloadResult:
        relative_path = resource_local_path(resource.url, main_host)
        local_path = output_dir / relative_path
        temp_path = local_path.with_name(local_path.name + ".part")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        last_error = "download failed"
        last_status: int | None = None
        for attempt in range(3):
            bytes_written = 0
            try:
                response = session_for_thread().get(
                    resource.url,
                    headers=replay_headers(resource.request_headers),
                    timeout=60,
                    stream=True,
                    allow_redirects=True,
                )
                last_status = response.status_code
                if response.status_code not in (200, 206):
                    last_error = f"HTTP {response.status_code}"
                    if response.status_code >= 500 and attempt < 2:
                        time.sleep(0.25 * (attempt + 1))
                        continue
                    return DownloadResult(
                        url=resource.url,
                        ok=False,
                        status=response.status_code,
                        error=last_error,
                        required=resource.required,
                    )
                response.raw.decode_content = False
                with temp_path.open("wb") as output:
                    while True:
                        chunk = response.raw.read(64 * 1024, decode_content=False)
                        if not chunk:
                            break
                        output.write(chunk)
                        bytes_written += len(chunk)

                declared = int(response.headers.get("content-length", "0") or 0)
                if declared and declared != bytes_written:
                    raise ValueError(
                        f"content-length mismatch: expected {declared}, got {bytes_written}"
                    )
                if not _complete_partial_response(response, bytes_written):
                    raise ValueError("incomplete HTTP 206 response")
                os.replace(temp_path, local_path)
                resource.local_path = relative_path.as_posix()
                return DownloadResult(
                    url=resource.url,
                    ok=True,
                    bytes_written=bytes_written,
                    local_path=local_path,
                    status=response.status_code,
                    required=resource.required,
                )
            except (
                OSError,
                ValueError,
                requests.RequestException,
                Urllib3HTTPError,
            ) as error:
                last_error = str(error)
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                if attempt < 2:
                    time.sleep(0.25 * (attempt + 1))
                    continue
        return DownloadResult(
            url=resource.url,
            ok=False,
            bytes_written=0,
            status=last_status,
            error=last_error,
            required=resource.required,
        )

    unique_resources: list[ResourceRecord] = []
    seen: set[str] = set()
    for resource in resources:
        if resource.method.upper() != "GET" or resource.url in seen:
            continue
        seen.add(resource.url)
        unique_resources.append(resource)

    results: list[DownloadResult] = []
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_map = {
            executor.submit(download_one, resource): resource for resource in unique_resources
        }
        for future in as_completed(future_map):
            results.append(future.result())

    return DownloadSummary(results=results)
