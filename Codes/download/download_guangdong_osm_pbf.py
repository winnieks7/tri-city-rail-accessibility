#!/usr/bin/env python3
"""Download and freeze the Geofabrik Guangdong OSM extract with checksums."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[2]
URL = "https://download.geofabrik.de/asia/china/guangdong-260824.osm.pbf"
MD5_URL = URL + ".md5"
RAW = ROOT / "Data/raw/transport/osm/guangdong_geofabrik_20260826.osm.pbf"
RAW_MD5 = ROOT / "Data/raw/transport/osm/guangdong_geofabrik_20260826.osm.pbf.md5"
METADATA = ROOT / "Data/metadata/transport/guangdong_geofabrik_20260826.json"


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    RAW.parent.mkdir(parents=True, exist_ok=True)
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "CarbonAnalysis-research/1.0"
    retry = Retry(
        total=12,
        connect=12,
        read=12,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    md5_response = session.get(MD5_URL, timeout=(20, 120))
    md5_response.raise_for_status()
    expected_md5 = md5_response.text.strip().split()[0].lower()

    if not RAW.exists():
        temporary = RAW.with_suffix(RAW.suffix + ".part")
        offset = temporary.stat().st_size if temporary.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        expected_bytes = 0
        for attempt in range(30):
            offset = temporary.stat().st_size if temporary.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            try:
                with session.get(
                    URL, headers=headers, stream=True, timeout=(30, 30)
                ) as response:
                    response.raise_for_status()
                    if offset and response.status_code != 206:
                        raise RuntimeError(
                            "server did not honor the byte-range request; partial file preserved"
                        )
                    content_range = response.headers.get("content-range", "")
                    if "/" in content_range:
                        expected_bytes = int(content_range.rsplit("/", 1)[1])
                    else:
                        response_bytes = int(response.headers.get("content-length", 0))
                        expected_bytes = offset + response_bytes if response_bytes else 0
                    mode = "ab" if offset else "wb"
                    with temporary.open(mode) as stream:
                        for block in response.iter_content(1024 * 1024):
                            if block:
                                stream.write(block)
                if not expected_bytes or temporary.stat().st_size >= expected_bytes:
                    break
            except requests.exceptions.RequestException:
                if attempt == 29:
                    raise
                continue
        actual_bytes = temporary.stat().st_size
        if expected_bytes and actual_bytes != expected_bytes:
            raise RuntimeError(
                f"content-length mismatch: expected {expected_bytes}, got {actual_bytes}; "
                "partial file preserved for resumption"
            )
        if digest(temporary, "md5") != expected_md5:
            raise RuntimeError(
                "Geofabrik MD5 mismatch before immutable promotion; file preserved"
            )
        temporary.replace(RAW)

    actual_md5 = digest(RAW, "md5")
    if actual_md5 != expected_md5:
        raise RuntimeError("existing immutable PBF does not match current frozen MD5")
    RAW_MD5.write_text(
        f"{expected_md5}  {RAW.name}\n", encoding="utf-8"
    )
    info = json.loads(
        subprocess.run(
            ["osmium", "fileinfo", "-e", "-j", str(RAW)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    metadata = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Geofabrik Guangdong (with Hong Kong and Macao) OpenStreetMap extract",
        "url": URL,
        "md5_url": MD5_URL,
        "license": "OpenStreetMap data under ODbL 1.0; Geofabrik extract",
        "local_file": str(RAW.relative_to(ROOT)),
        "bytes": RAW.stat().st_size,
        "md5": actual_md5,
        "sha256": digest(RAW, "sha256"),
        "osmium_version": subprocess.run(
            ["osmium", "--version"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0],
        "pbf_header_and_extended_info": info,
        "raw_immutable": True,
        "accessibility_outcome_read": False,
    }
    METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
