#!/usr/bin/env python3
"""
Step 2 (part 1): create the seven class folders, named EXACTLY as the Roboflow
class names, plus a manifest stub for provenance tracking.

Usage:  python scripts/00_scaffold.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASET, QUARANTINE, REPORTS, class_dir, class_names, ensure_dirs, load_config

MANIFEST_HEADER = [
    "filename", "class", "source", "query", "source_url",
    "width", "height", "phash", "collected_utc", "status", "notes",
]


def main() -> int:
    cfg = load_config()
    ensure_dirs(cfg)
    QUARANTINE.mkdir(parents=True, exist_ok=True)

    for name in class_names(cfg):
        (QUARANTINE / name).mkdir(parents=True, exist_ok=True)

    manifest = REPORTS / "manifest.csv"
    if not manifest.exists():
        with open(manifest, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(MANIFEST_HEADER)

    print(f"Dataset root : {DATASET}")
    print(f"Quarantine   : {QUARANTINE}")
    print(f"Manifest     : {manifest}")
    print()
    print("Class folders created:")
    for c in cfg["classes"]:
        d = class_dir(c["name"])
        print(f"  [{c['id']}] {d}")
    print()
    print(f"Target per class: {cfg['project']['target_per_class']} "
          f"(min {cfg['project']['min_per_class']}, max {cfg['project']['max_per_class']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
