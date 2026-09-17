#!/usr/bin/env python3
"""Archive official aggregate sources used to enumerate the D-city rail denominator."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTDIR = ROOT / "Data/raw/transport/official_sources/denominator"
METADATA = ROOT / "Data/metadata/transport/d_denominator_source_archive.json"

SOURCES = [
    {
        "id": "GZ_TRANSPORT_2023",
        "authority": "Guangzhou municipal transport/planning authorities",
        "url": "https://www.gz.gov.cn/attachment/7/7643/7643687/9792745.pdf",
        "file": "guangzhou_transport_development_report_2023.pdf",
        "role": "official 2023 urban rail line, tram and network denominator",
    },
    {
        "id": "GZ_TRANSPORT_2024",
        "authority": "Guangzhou municipal transport/planning authorities",
        "url": "https://ghzyj.gz.gov.cn/attachment/7/7806/7806901/10233239.pdf",
        "file": "guangzhou_transport_development_report_2024.pdf",
        "role": "official 2024 openings, active lines, station suspensions and network denominator",
    },
    {
        "id": "FS_METRO_2023_SOCIAL",
        "authority": "Foshan Metro Group",
        "url": "https://www.fmetro.net/upload/main/contentmanage/article/file/2024/08/19/202408191534278940.pdf",
        "file": "foshan_metro_social_value_report_2023.pdf",
        "role": "operator report for active metro denominator and construction status",
    },
    {
        "id": "DG_URBAN_RAIL_TRACKING",
        "authority": "Dongguan Municipal Transportation Bureau",
        "url": "https://gdjt.dg.gov.cn/attachment/0/337/337848/4374733.pdf",
        "file": "dongguan_urban_rail_plan_tracking_evaluation.pdf",
        "role": "official active urban metro denominator and Line 2 specification",
    },
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, target: Path) -> None:
    if target.exists():
        return
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(
        url, headers={"User-Agent": "CarbonAnalysis/transport-study"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        with partial.open("wb") as stream:
            while True:
                block = response.read(4 * 1024 * 1024)
                if not block:
                    break
                stream.write(block)
    if partial.stat().st_size < 1024 or partial.read_bytes()[:4] != b"%PDF":
        raise RuntimeError(f"Downloaded file is not a valid PDF header: {target.name}")
    os.replace(partial, target)


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    archived = []
    for item in SOURCES:
        target = OUTDIR / item["file"]
        fetch(item["url"], target)
        archived.append(
            {
                **item,
                "local_file": str(target.relative_to(ROOT)),
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
            }
        )

    record = {
        "archive": "development-city rail denominator aggregate sources",
        "cities": ["Guangzhou", "Foshan", "Dongguan"],
        "outcome_data_read": False,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": archived,
    }
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    METADATA.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
