#!/usr/bin/env python3
"""Download the two immutable JRC GSW v1.4 occurrence tiles covering the GBA."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTDIR = ROOT / "Data/raw/controls/jrc_gsw_v1_4_occurrence"
METADATA = ROOT / "Data/metadata/jrc_gsw_v1_4_occurrence.json"
BASE = "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence"
SOURCE_PAGE = "https://global-surface-water.appspot.com/download"

TILES = {
    "occurrence_100E_30Nv1_4_2021.tif": {
        "size": 47_460_260,
        "md5": "cffcd616364b43a86165cee1f33a135b",
    },
    "occurrence_110E_30Nv1_4_2021.tif": {
        "size": 74_075_982,
        "md5": "8d2c6507e1212adaa822441c68e30668",
    },
}


def digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, target: Path, expected_size: int, expected_md5: str) -> None:
    if target.exists():
        if target.stat().st_size != expected_size or digest(target, "md5") != expected_md5:
            raise RuntimeError(f"Immutable target exists but fails validation: {target}")
        return

    partial = target.with_suffix(target.suffix + ".part")
    last_error = None
    for _attempt in range(10):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == expected_size:
            break
        if offset > expected_size:
            raise RuntimeError(f"Partial file exceeds expected size: {partial}")

        headers = {"User-Agent": "CarbonAnalysis/transport-study"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                mode = "ab" if offset and response.status == 206 else "wb"
                with partial.open(mode) as stream:
                    while True:
                        block = response.read(8 * 1024 * 1024)
                        if not block:
                            break
                        stream.write(block)
            last_error = None
        except (OSError, EOFError) as exc:
            # Preserve validated bytes and resume from the next byte.
            last_error = repr(exc)

    if not partial.exists() or partial.stat().st_size != expected_size:
        raise RuntimeError(
            f"Size mismatch for {partial.name}: "
            f"{partial.stat().st_size if partial.exists() else 0} != {expected_size}; "
            f"last_error={last_error}"
        )
    if digest(partial, "md5") != expected_md5:
        raise RuntimeError(f"MD5 mismatch for {partial.name}")
    os.replace(partial, target)


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    records = []
    for name, expected in TILES.items():
        url = f"{BASE}/{name}"
        target = OUTDIR / name
        download(url, target, expected["size"], expected["md5"])
        records.append(
            {
                "file": str(target.relative_to(ROOT)),
                "url": url,
                "bytes": target.stat().st_size,
                "md5": digest(target, "md5"),
                "sha256": digest(target, "sha256"),
            }
        )

    metadata = {
        "dataset": "JRC Global Surface Water occurrence",
        "version": "v1.4",
        "observation_period": "1984-2021",
        "native_resolution_m": 30,
        "download_page": SOURCE_PAGE,
        "license": "Copernicus Programme, free of charge without restriction of use",
        "required_map_attribution": "Source: EC JRC/Google",
        "study_role": "permanent-water exclusion only",
        "frozen_threshold": "occurrence >= 90%",
        "outcome_data_read": False,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "tiles": records,
    }
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
