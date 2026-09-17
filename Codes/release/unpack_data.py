#!/usr/bin/env python3
"""Safely unpack the published numerical bundles without overwriting differences."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    entries = json.loads((ROOT / "DataBundles/bundles.json").read_text())
    planned = []
    for entry in entries:
        path = ROOT / entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Bundle checksum mismatch: {path.name}")
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                relative = Path(item.filename)
                if relative.is_absolute() or ".." in relative.parts or not item.filename.startswith(("Data/", "Figures/", "Results/")):
                    raise RuntimeError(f"Unexpected archive path: {item.filename}")
                destination = (ROOT / relative).resolve()
                if not destination.is_relative_to(ROOT):
                    raise RuntimeError(f"Archive path escapes repository: {relative}")
                data = archive.read(item)
                if destination.exists() and destination.read_bytes() != data:
                    raise RuntimeError(f"Refusing to overwrite different file: {relative}")
                planned.append((destination, data))
    for destination, data in planned:
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                output.write(data)
    print(f"Verified and made available {len(planned)} bundle members.")


if __name__ == "__main__":
    main()
