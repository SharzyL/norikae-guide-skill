#!/usr/bin/env python3
"""Build a distributable zip of the norikae-guide skill."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "norikae-guide-skill.zip"

INCLUDE = [
    "SKILL.md",
    "references/yahoo-transit-params.md",
    "references/natural-language-examples.md",
    "scripts/fetch_norikae_routes.py",
    "scripts/fetch_timetable.py",
]


def main() -> None:
    with ZipFile(OUT, "w") as zf:
        for rel in INCLUDE:
            path = ROOT / rel
            if not path.exists():
                print(f"  skip (missing): {rel}")
                continue
            zf.write(path, rel)
            print(f"  added: {rel}")

    print(f"\n=> {OUT}  ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
