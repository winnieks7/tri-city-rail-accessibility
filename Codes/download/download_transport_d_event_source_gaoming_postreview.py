#!/usr/bin/env python3
"""Persist a replacement institutional record for the Gaoming Tram opening."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Data/raw/transport/official_sources/d_event_source_gaoming_postreview_20260827"
META = ROOT / "Data/metadata/transport/d_event_source_gaoming_postreview_20260827.json"
URL = "https://pc.nfnews.com/9249/2981690.html"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "fs_tram_gm1_opening_nanfangplus.html"
    if not target.exists():
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
                URL,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip())
    text = " ".join(
        BeautifulSoup(target.read_bytes(), "html.parser")
        .get_text(" ", strip=True)
        .split()
    )
    phrase_checks = {
        phrase: phrase in text
        for phrase in ["高明有轨电车", "2019年12月30日", "初期运营"]
    }
    payload = {
        "archive": "Gaoming Tram post-review institutional-source replacement",
        "created_after_D_outcome_opening": True,
        "role": (
            "provenance persistence only; does not change the event date, topology, "
            "eligibility, package, or numerical result"
        ),
        "original_crrc_endpoint_status": "TLS retrieval failure",
        "record": {
            "id": "FS_TRAM_GM1_OPENING_NANFANGPLUS",
            "url": URL,
            "publisher": "Nanfang Plus",
            "source_class": "provincial state-media institutional record",
            "events": ["D2019_E03_FS_TRAM_GM1"],
            "verification_claim": "line was in initial passenger operation from 2019-12-30",
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "local_file": str(target.relative_to(ROOT)),
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
            "phrase_checks": phrase_checks,
            "verification_passed": all(phrase_checks.values()),
        },
    }
    payload["passed"] = bool(
        payload["record"]["verification_passed"]
        and payload["record"]["bytes"] > 1000
    )
    META.parent.mkdir(parents=True, exist_ok=True)
    META.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
