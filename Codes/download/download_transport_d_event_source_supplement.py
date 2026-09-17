#!/usr/bin/env python3
"""Archive primary URLs cited by D event components but absent from the first ledger."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Data/raw/transport/official_sources/d_event_source_supplement"
META = ROOT / "Data/metadata/transport/d_event_source_supplement_20260826.json"
SOURCES = [
    {
        "id": "FS_TRAM_GM1_OPENING_CRRC",
        "url": "https://crrcgc.cc/crrcgc/2020-01/07/article_D42124F3812546CDB836432DA7692DA3.html",
        "file": "fs_tram_gm1_opening_crrc.html",
        "events": ["D2019_E03_FS_TRAM_GM1"],
    },
    {
        "id": "GZ_TRAM_HP1_FIRST_GZGOV",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/content/post_6804331.html",
        "file": "gz_tram_hp1_first_gzgov.html",
        "events": ["D2020_E01_GZ_TRAM_HP1_FIRST"],
    },
    {
        "id": "GZ_TRAM_HP1_FULL_ANNUAL_REPORT",
        "url": "https://ghzyj.gz.gov.cn/attachment/7/7387/7387273/7756059.pdf",
        "file": "gz_tram_hp1_full_annual_report.pdf",
        "events": ["D2020_E04_GZ_TRAM_HP1_FULL"],
    },
    {
        "id": "FS_TRAM_NH1_GD_TRANSPORT",
        "url": "https://td.gd.gov.cn/gkmlpt/content/4/4055/post_4055183.html",
        "file": "fs_tram_nh1_openings_gd_transport.html",
        "events": ["D2021_E01_FS_TRAM_NH1_FIRST", "D2022_E04_FS_TRAM_NH1_FULL"],
    },
    {
        "id": "FS_M2_PHASE1_NDRC",
        "url": "https://www.ndrc.gov.cn/fggz/zcssfz/dffz/202202/t20220228_1317858_ext.html",
        "file": "fs_m2_phase1_ndrc.html",
        "events": ["D2021_E03_FS_M2_PHASE1"],
    },
    {
        "id": "GZ_M7_WEST_NDRC",
        "url": "https://www.ndrc.gov.cn/fggz/zcssfz/dffz/202207/t20220729_1332236.html",
        "file": "gz_m7_west_ndrc.html",
        "events": ["D2022_E02_GZ_M7_WEST"],
    },
    {
        "id": "FS_M3_FIRST_NDRC",
        "url": "https://www.ndrc.gov.cn/fggz/zcssfz/dffz/202302/t20230228_1350080.html",
        "file": "fs_m3_first_ndrc.html",
        "events": ["D2022_E05_FS_M3_FIRST"],
    },
    {
        "id": "GZ_M5_M7_2023_GZGOV",
        "url": "https://www.gz.gov.cn/zwfw/zxfw/jtfw/content/post_9409437.html",
        "file": "gz_m5_m7_2023_gzgov.html",
        "events": ["D2023_E01_GZ_M5_EAST", "D2023_E02_GZ_M7_PHASE2"],
    },
    {
        "id": "FS_M3_2024_PRESS_CONFERENCE",
        "url": "https://www.foshannews.net/fsxwfb/2017/lcfbh/fbh1102_40754/",
        "file": "fs_m3_2024_press_conference.html",
        "events": ["D2024_E03_FS_M3_TWO_SECTIONS"],
    },
    {
        "id": "GZ_2024_RAIL_ANNUAL_REPORT",
        "url": "https://ghzyj.gz.gov.cn/attachment/7/7806/7806901/10233239.pdf",
        "file": "gz_2024_rail_annual_report.pdf",
        "events": [
            "D2024_E04_GZ_M3_EAST",
            "D2024_E05_HZ1_TOWER_CLOSURE",
            "D2024_E06_GZ_M11_SHAHE",
        ],
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_payload(path: Path) -> bool:
    data = path.read_bytes()[:32]
    if path.suffix == ".pdf":
        return data.startswith(b"%PDF-")
    lowered = data.lower()
    return b"<html" in lowered or b"<!doctype" in lowered or b"<?xml" in lowered


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) CarbonAnalysis/1.0 source-archive"
        }
    )
    records = []
    for source in SOURCES:
        target = OUT / source["file"]
        record = {**source, "local_file": str(target.relative_to(ROOT))}
        if target.exists() and valid_payload(target):
            record.update(
                {
                    "status": "existing_valid",
                    "bytes": target.stat().st_size,
                    "sha256": sha256(target),
                }
            )
            records.append(record)
            continue
        error = None
        for attempt in range(1, 4):
            try:
                response = session.get(source["url"], timeout=60, allow_redirects=True)
                response.raise_for_status()
                target.write_bytes(response.content)
                if not valid_payload(target):
                    raise RuntimeError("downloaded payload failed PDF/HTML magic check")
                record.update(
                    {
                        "status": "downloaded",
                        "http_status": response.status_code,
                        "final_url": response.url,
                        "content_type": response.headers.get("content-type"),
                        "bytes": target.stat().st_size,
                        "sha256": sha256(target),
                    }
                )
                error = None
                break
            except Exception as exc:  # network receipts must preserve failures
                error = f"{type(exc).__name__}: {exc}"
                if target.exists() and not valid_payload(target):
                    target.unlink()
                time.sleep(attempt)
        if error is not None:
            record.update({"status": "failed", "error": error})
        records.append(record)
    metadata = {
        "archive": "D event primary-source supplement",
        "created_after_D_outcome_opening": True,
        "role": "provenance persistence only; does not change event dates, packages, topology or numerical outcomes",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": records,
        "counts": {
            "requested": len(records),
            "archived": sum(item["status"] in {"downloaded", "existing_valid"} for item in records),
            "failed": sum(item["status"] == "failed" for item in records),
            "covered_event_ids": len(
                {
                    event
                    for item in records
                    if item["status"] in {"downloaded", "existing_valid"}
                    for event in item["events"]
                }
            ),
        },
    }
    META.parent.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0 if metadata["counts"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
