from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from urllib.parse import urljoin, urlparse

from .discovery import GAME_EXTENSIONS
from .models import ResourceRecord


QUOTED_VALUE_RE = re.compile(r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.DOTALL)
SCANNABLE_EXTENSIONS = (".html", ".htm", ".js", ".mjs", ".css", ".json")


def _clean_reference(value: str) -> str:
    return (
        value.replace(r"\/", "/")
        .replace(r"\u002f", "/")
        .replace(r"\u002F", "/")
        .strip()
    )


def _has_resource_extension(reference: str) -> bool:
    try:
        path = urlparse(reference).path.lower()
    except ValueError:
        return False
    return path.endswith(GAME_EXTENSIONS)


def extract_resource_urls(text: str, source_url: str, engine: str = "unknown") -> set[str]:
    del engine  # Extension coverage is shared; engine detection determines which sources are scanned.
    urls: set[str] = set()
    for match in QUOTED_VALUE_RE.finditer(text):
        reference = _clean_reference(match.group("value"))
        if not reference or reference.startswith(("data:", "blob:", "javascript:", "#")):
            continue
        if not _has_resource_extension(reference):
            continue
        try:
            resolved = urljoin(source_url, reference)
        except ValueError:
            continue
        if urlparse(resolved).scheme in {"http", "https"}:
            urls.add(resolved)
    return urls


def _is_scannable(resource: ResourceRecord) -> bool:
    path = urlparse(resource.url).path.lower()
    content_type = resource.response_headers.get("content-type", "").lower()
    return path.endswith(SCANNABLE_EXTENSIONS) or any(
        marker in content_type
        for marker in ("text/", "javascript", "json", "css", "html")
    )


def supplement_resources(
    resources: Iterable[ResourceRecord],
    frame_engines: dict[str, str],
    fetch_text: Callable[[str, dict[str, str]], str | None],
) -> list[ResourceRecord]:
    resource_list = list(resources)
    known_urls = {resource.url for resource in resource_list}
    supplemented: list[ResourceRecord] = []

    for source in resource_list:
        if not _is_scannable(source):
            continue
        text = fetch_text(source.url, source.request_headers)
        if not text:
            continue
        engine = frame_engines.get(source.frame_url, "unknown")
        for url in sorted(extract_resource_urls(text, source.url, engine)):
            if url in known_urls:
                continue
            known_urls.add(url)
            headers = dict(source.request_headers)
            headers["referer"] = source.url
            supplemented.append(
                ResourceRecord(
                    url=url,
                    method="GET",
                    resource_type="other",
                    frame_url=source.frame_url,
                    frame_ancestors=source.frame_ancestors,
                    request_headers=headers,
                    discovery_method=f"manifest:{engine}",
                )
            )
    return supplemented
