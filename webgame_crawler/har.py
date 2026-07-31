import json
import os
from pathlib import Path
import zipfile

from .models import HarArchiveInfo


def inspect_har(path: Path) -> HarArchiveInfo:
    try:
        size = path.stat().st_size
        if size == 0:
            raise OSError("HAR archive is empty")

        with zipfile.ZipFile(path) as archive:
            member_names = archive.namelist()
            har_names = [name for name in member_names if name.endswith(".har")]
            if len(har_names) != 1:
                raise KeyError("expected exactly one .har member")

            har = json.loads(archive.read(har_names[0]))
            entries = har["log"]["entries"]
            body_count = 0
            for entry in entries:
                content = entry["response"]["content"]
                attachment = content.get("_file")
                if attachment:
                    if attachment not in member_names:
                        raise KeyError(attachment)
                    body_count += 1
                elif content.get("text"):
                    body_count += 1

        valid = bool(entries) and body_count > 0
        error = None if valid else "HAR archive has no entries or stored response bodies"
        return HarArchiveInfo(path, valid, size, len(entries), body_count, error)
    except (
        OSError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
        UnicodeDecodeError,
        KeyError,
        TypeError,
    ) as error:
        return HarArchiveInfo(path, False, error=str(error))


def install_har(source: Path, output_dir: Path) -> Path:
    destination = output_dir / "_crawl" / "capture.har.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)
    return destination
