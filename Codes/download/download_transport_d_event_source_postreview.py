#!/usr/bin/env python3
"""Persist replacement institutional evidence for reviewer-flagged rail events."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Data/raw/transport/official_sources/d_event_source_postreview_20260827"
META = ROOT / "Data/metadata/transport/d_event_source_postreview_20260827.json"

SOURCES = [
    {
        "id": "FS_TRAM_NH1_FIRST_HUACHENG",
        "url": "https://huacheng.gz-cmc.com/pages/2021/08/18/d0f170b07d6d47158e05ffd4bd2c96ab.html",
        "file": "fs_tram_nh1_first_huacheng.html",
        "publisher": "Guangzhou Daily Huacheng",
        "source_class": "municipal state-media institutional record",
        "events": ["D2021_E01_FS_TRAM_NH1_FIRST"],
        "required_phrases": ["2021", "08", "18", "首通段", "开通"],
        "verification_claim": "first section opened to the public at noon on 2021-08-18",
    },
    {
        "id": "FS_TRAM_NH1_FIRST_CSCEC",
        "url": "https://www.cscec.com/zgjz_new/xwzx_new/zqydt_new/202108/3386101.html",
        "file": "fs_tram_nh1_first_cscec.html",
        "publisher": "China State Construction Engineering Corporation",
        "source_class": "state-owned project participant institutional record",
        "events": ["D2021_E01_FS_TRAM_NH1_FIRST"],
        "required_phrases": ["8月18日", "南海有轨电车", "首通段", "正式通车"],
        "verification_claim": "first section formally opened on 2021-08-18",
    },
    {
        "id": "FS_TRAM_NH1_FULL_CSCEC",
        "url": "https://www.cscec.com/xwzx_new/zqydt_new/202212/3604924.html",
        "file": "fs_tram_nh1_full_cscec.html",
        "publisher": "China State Construction Engineering Corporation",
        "source_class": "state-owned project participant institutional record",
        "events": ["D2022_E04_FS_TRAM_NH1_FULL"],
        "required_phrases": ["11月29日", "南海有轨电车1号线", "全线贯通"],
        "verification_claim": "remaining section entered service and the line became complete on 2022-11-29",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def visible_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(
            "post-review raw source directory already contains files; raw evidence is immutable"
        )
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for source in SOURCES:
        target = OUT / source["file"]
        completed = subprocess.run(
            [
                "curl",
                "--location",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "60",
                "--user-agent",
                "Mozilla/5.0 CarbonAnalysis/1.1 post-review-source-archive",
                "--output",
                str(target),
                source["url"],
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"curl failed for {source['id']}: {completed.stderr.strip()}"
            )
        content = target.read_bytes()
        text = visible_text(content)
        phrase_checks = {
            phrase: phrase in text for phrase in source["required_phrases"]
        }
        record = {
            **source,
            "download_status": "downloaded",
            "download_transport": "curl --location --fail",
            "final_url": source["url"],
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "local_file": str(target.relative_to(ROOT)),
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
            "phrase_checks": phrase_checks,
            "verification_passed": all(phrase_checks.values()),
        }
        records.append(record)

    checks = {
        "three_replacement_records_archived": len(records) == 3,
        "all_payloads_nonempty": all(item["bytes"] > 1000 for item in records),
        "all_required_phrases_present": all(
            item["verification_passed"] for item in records
        ),
        "both_nanhai_events_have_persistent_replacement": {
            event
            for item in records
            if item["verification_passed"]
            for event in item["events"]
        }
        == {
            "D2021_E01_FS_TRAM_NH1_FIRST",
            "D2022_E04_FS_TRAM_NH1_FULL",
        },
    }
    payload = {
        "archive": "D event post-review institutional-source replacement",
        "created_after_D_outcome_opening": True,
        "role": (
            "provenance persistence only; does not change event dates, packages, "
            "topology, eligibility, or numerical outcomes"
        ),
        "original_broken_endpoint": (
            "https://td.gd.gov.cn/gkmlpt/content/4/4055/post_4055183.html"
        ),
        "original_endpoint_status_at_postreview": "HTTP 404",
        "records": records,
        "checks": checks,
        "passed": all(checks.values()),
    }
    META.parent.mkdir(parents=True, exist_ok=True)
    META.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
