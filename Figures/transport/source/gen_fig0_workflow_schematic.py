#!/usr/bin/env python3
"""Render the canonical Figure 1 workflow from its editable Graphviz source."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIGURE_ROOT = HERE.parent
DOT_SOURCE = HERE / "fig0_workflow_graphviz_revised.dot"


def render(dot: str, fmt: str, output: Path, *, dpi: int | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [dot, f"-T{fmt}"]
    if dpi is not None:
        command.append(f"-Gdpi={dpi}")
    command.extend([str(DOT_SOURCE), "-o", str(output)])
    subprocess.run(command, check=True)


def main() -> None:
    dot = shutil.which("dot")
    if dot is None:
        raise SystemExit("Graphviz 'dot' was not found on PATH")
    if not DOT_SOURCE.is_file():
        raise SystemExit(f"Missing Graphviz source: {DOT_SOURCE}")

    render(dot, "pdf", FIGURE_ROOT / "main" / "fig0_workflow_schematic.pdf")
    render(dot, "svg", FIGURE_ROOT / "svg" / "main" / "fig0_workflow_schematic.svg")
    render(
        dot,
        "png",
        FIGURE_ROOT / "main" / "fig0_workflow_schematic.png",
        dpi=300,
    )


if __name__ == "__main__":
    main()
