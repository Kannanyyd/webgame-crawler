from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ResourceRecord:
    url: str
    method: str = "GET"
    resource_type: str = "other"
    frame_url: str = ""
    frame_ancestors: tuple[str, ...] = ()
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    status: int | None = None
    encoded_size: int = 0
    failure: str | None = None
    discovery_method: str = "browser"
    local_path: str | None = None


@dataclass(slots=True)
class FrameSnapshot:
    url: str
    parent_url: str = ""
    ancestors: tuple[str, ...] = ()
    canvas_count: int = 0
    engine: str = "unknown"


@dataclass(slots=True)
class FrameSignal:
    frame: FrameSnapshot
    resource_count: int = 0
    game_like_count: int = 0
    encoded_size: int = 0
    score: float = 0.0


@dataclass(slots=True)
class CaptureResult:
    requested_url: str
    final_url: str
    title: str
    frames: list[FrameSnapshot]
    resources: list[ResourceRecord]
    selected_frames: list[FrameSignal]
    selected_resources: list[ResourceRecord]
    cookies: list[dict[str, Any]] = field(default_factory=list)
    user_agent: str = ""


@dataclass(slots=True)
class DownloadResult:
    url: str
    ok: bool
    bytes_written: int = 0
    local_path: Path | None = None
    status: int | None = None
    error: str | None = None
    skipped: bool = False


@dataclass(slots=True)
class DownloadSummary:
    results: list[DownloadResult] = field(default_factory=list)

    @property
    def downloaded(self) -> int:
        return sum(1 for result in self.results if result.ok and not result.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for result in self.results if result.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for result in self.results if not result.ok)

    @property
    def encoded_bytes(self) -> int:
        return sum(result.bytes_written for result in self.results if result.ok)
