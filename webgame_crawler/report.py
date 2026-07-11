from __future__ import annotations

import json
from pathlib import Path

from .models import CaptureResult, DownloadSummary, ResourceRecord


def _integer_header(resource: ResourceRecord, name: str) -> int:
    try:
        return int(resource.response_headers.get(name, "0") or 0)
    except ValueError:
        return 0


def write_reports(
    capture: CaptureResult,
    resources: list[ResourceRecord],
    downloads: DownloadSummary,
    output_dir: Path,
) -> dict:
    crawl_dir = output_dir / "_crawl"
    crawl_dir.mkdir(parents=True, exist_ok=True)

    resource_map = [
        {
            "url": resource.url,
            "method": resource.method,
            "type": resource.resource_type,
            "frameUrl": resource.frame_url,
            "status": resource.status,
            "encodedSize": resource.encoded_size,
            "decodedSize": _integer_header(resource, "x-amz-meta-uncompressed-length"),
            "discoveryMethod": resource.discovery_method,
            "localPath": resource.local_path,
            "failure": resource.failure,
        }
        for resource in resources
    ]
    failures = [
        {
            "url": result.url,
            "status": result.status,
            "bytesWritten": result.bytes_written,
            "error": result.error,
        }
        for result in downloads.results
        if not result.ok
    ]
    summary = {
        "requestedUrl": capture.requested_url,
        "finalUrl": capture.final_url,
        "title": capture.title,
        "selectedFrames": [
            {
                "url": signal.frame.url,
                "engine": signal.frame.engine,
                "score": round(signal.score, 2),
                "resourceCount": signal.resource_count,
                "encodedSize": signal.encoded_size,
            }
            for signal in capture.selected_frames
        ],
        "captured": len(capture.resources),
        "included": len(resources),
        "excluded": max(0, len(capture.resources) - len(capture.selected_resources)),
        "downloaded": downloads.downloaded,
        "skipped": downloads.skipped,
        "failed": downloads.failed,
        "requiredFailed": downloads.required_failed,
        "encodedBytes": downloads.encoded_bytes,
        "knownDecodedBytes": sum(
            _integer_header(resource, "x-amz-meta-uncompressed-length")
            for resource in resources
        ),
    }

    (crawl_dir / "resource-map.json").write_text(
        json.dumps(resource_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (crawl_dir / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (crawl_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
