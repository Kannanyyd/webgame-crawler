from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from urllib.parse import urljoin, urlparse

from .discovery import GAME_EXTENSIONS
from .models import ResourceRecord


QUOTED_VALUE_RE = re.compile(r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.DOTALL)
SCANNABLE_EXTENSIONS = (".html", ".htm", ".js", ".mjs", ".css", ".json")
COCOS_BASE64_VALUES = {
    char: index
    for index, char in enumerate(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    )
}
COCOS_NATIVE_EXTENSIONS = {
    "cc.Texture2D": (".png", ".jpg", ".jpeg", ".webp", ".pvr", ".pkm"),
    "cc.AudioClip": (".mp3", ".ogg", ".wav", ".m4a"),
    "cc.BitmapFont": (".fnt", ".font"),
    "sp.SkeletonData": (".json", ".bin", ".atlas"),
}
COCOS_UNKNOWN_NATIVE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".webp",
    ".mp3",
    ".ogg",
    ".wav",
    ".json",
    ".bin",
    ".atlas",
)


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


def _valid_reference(reference: str) -> bool:
    if len(reference) > 2_048 or any(char in reference for char in "\r\n\t{}();"):
        return False
    lowered = reference.lower()
    for scheme in ("http://", "https://"):
        position = lowered.find(scheme)
        if position > 0:
            return False
    filename = urlparse(reference).path.rsplit("/", 1)[-1].lower()
    if filename in GAME_EXTENSIONS:
        return False
    return True


def _decode_cocos_uuid(value: str) -> str:
    base, separator, suffix = value.partition("@")
    if len(base) != 22:
        return value
    try:
        decoded = [""] * 36
        for position in (8, 13, 18, 23):
            decoded[position] = "-"
        writable = [index for index, char in enumerate(decoded) if not char]
        decoded[0], decoded[1] = base[0], base[1]
        target = 2
        hex_values = "0123456789abcdef"
        for index in range(2, 22, 2):
            left = COCOS_BASE64_VALUES[base[index]]
            right = COCOS_BASE64_VALUES[base[index + 1]]
            for part in (left >> 2, ((left & 3) << 2) | (right >> 4), right & 15):
                decoded[writable[target]] = hex_values[part]
                target += 1
        result = "".join(decoded)
        return result + separator + suffix
    except (KeyError, IndexError):
        return value


def _cocos_versioned_import_urls(text: str, source_url: str) -> set[str]:
    try:
        config = json.loads(text)
    except (TypeError, ValueError):
        return set()
    if not isinstance(config, dict):
        return set()
    versions = config.get("versions")
    if not isinstance(versions, dict) or not isinstance(versions.get("import"), list):
        return set()

    uuids = [
        _decode_cocos_uuid(value) if isinstance(value, str) else value
        for value in config.get("uuids", [])
    ]
    extension_by_uuid: dict[str, str] = {}
    extension_map = config.get("extensionMap")
    if not isinstance(extension_map, dict):
        extension_map = {}
    for extension, keys in extension_map.items():
        if not isinstance(extension, str) or not isinstance(keys, list):
            continue
        resolved_extension = ".bin" if extension == ".cconb" else extension
        for key in keys:
            index = None
            if isinstance(key, int):
                index = key
            elif isinstance(key, str) and key.isdecimal():
                index = int(key)
            if index is not None:
                if index < 0 or index >= len(uuids):
                    continue
                key = uuids[index]
            if isinstance(key, str):
                extension_by_uuid[_decode_cocos_uuid(key)] = resolved_extension
    import_base = config.get("importBase") or "import"
    entries = versions["import"]
    urls: set[str] = set()
    for index in range(0, len(entries) - 1, 2):
        key, version = entries[index], entries[index + 1]
        if isinstance(key, int):
            if key < 0 or key >= len(uuids):
                continue
            key = uuids[key]
        if not isinstance(key, str) or not isinstance(version, str):
            continue
        uuid = _decode_cocos_uuid(key)
        extension = extension_by_uuid.get(uuid, ".json")
        reference = f"{import_base}/{uuid[:2]}/{uuid}.{version}{extension}"
        urls.add(urljoin(source_url, reference))
    return urls


def _cocos_versioned_native_urls(text: str, source_url: str) -> set[str]:
    try:
        config = json.loads(text)
    except (TypeError, ValueError):
        return set()
    if not isinstance(config, dict):
        return set()
    versions = config.get("versions")
    if not isinstance(versions, dict) or not isinstance(versions.get("native"), list):
        return set()

    uuids = [
        _decode_cocos_uuid(value) if isinstance(value, str) else value
        for value in config.get("uuids", [])
    ]
    types = config.get("types", [])
    type_by_uuid: dict[str, str] = {}
    for key, path_info in config.get("paths", {}).items():
        try:
            uuid = uuids[int(key)]
            type_index = path_info[1]
            if isinstance(uuid, str) and isinstance(type_index, int):
                type_by_uuid[uuid] = types[type_index]
        except (IndexError, KeyError, TypeError, ValueError):
            continue

    native_base = config.get("nativeBase") or "native"
    entries = versions["native"]
    urls: set[str] = set()
    for index in range(0, len(entries) - 1, 2):
        key, version = entries[index], entries[index + 1]
        if isinstance(key, int):
            if key < 0 or key >= len(uuids):
                continue
            key = uuids[key]
        if not isinstance(key, str) or not isinstance(version, str):
            continue
        uuid = _decode_cocos_uuid(key)
        extensions = COCOS_NATIVE_EXTENSIONS.get(
            type_by_uuid.get(uuid, ""), COCOS_UNKNOWN_NATIVE_EXTENSIONS
        )
        for extension in extensions:
            reference = f"{native_base}/{uuid[:2]}/{uuid}.{version}{extension}"
            urls.add(urljoin(source_url, reference))
    return urls


def extract_resource_urls(text: str, source_url: str, engine: str = "unknown") -> set[str]:
    urls: set[str] = set()
    for match in QUOTED_VALUE_RE.finditer(text):
        reference = _clean_reference(match.group("value"))
        if not reference or reference.startswith(("data:", "blob:", "javascript:", "#")):
            continue
        if not _valid_reference(reference):
            continue
        if not _has_resource_extension(reference):
            continue
        try:
            resolved = urljoin(source_url, reference)
        except ValueError:
            continue
        if urlparse(resolved).scheme in {"http", "https"}:
            urls.add(resolved)
    if engine == "cocos":
        urls.update(_cocos_versioned_import_urls(text, source_url))
        urls.update(_cocos_versioned_native_urls(text, source_url))
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
    probe_urls: Callable[[set[str], dict[str, str]], set[str]] | None = None,
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
        discovered = extract_resource_urls(text, source.url, engine)
        if probe_urls is not None:
            unresolved: set[str] = set()
            declared_imports: set[str] = set()
            if engine == "cocos":
                declared_imports = _cocos_versioned_import_urls(
                    text, source.url
                )
                native_candidates = _cocos_versioned_native_urls(text, source.url)
                discovered.difference_update(native_candidates)
                known_native_stems = {
                    url.rsplit(".", 1)[0]
                    for url in native_candidates
                    if url in known_urls
                }
                unresolved = {
                    url
                    for url in native_candidates
                    if url.rsplit(".", 1)[0] not in known_native_stems
                }
            unverified = {
                url
                for url in discovered
                if url not in known_urls and url not in declared_imports
            }
            verified = probe_urls(
                unverified | unresolved, source.request_headers
            )
            discovered = {
                url for url in discovered if url in known_urls
            } | declared_imports | verified
        for url in sorted(discovered):
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
                    required=False,
                )
            )
    return supplemented
