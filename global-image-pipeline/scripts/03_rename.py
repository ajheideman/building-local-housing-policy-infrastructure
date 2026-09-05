#!/usr/bin/env python3
"""
Step 2 (part 2): give every surviving image its final sequential name,
exactly as the instructions specify -- e.g. exterior_wall_damage_001.jpg.

Renaming happens only AFTER QC so the numbering has no gaps.  Already-named
files keep their number; new arrivals continue the sequence, so this is safe
to re-run after each collection round.

Usage:
  python scripts/03_rename.py
  python scripts/03_rename.py --dry-run
  python scripts/03_rename.py --classes window_damage --renumber   # force 001..N
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPORTS, class_dir, class_names, iter_images, load_config

FINAL = re.compile(r"^(?P<cls>[a-z_]+)_(?P<num>\d{3,})\.(?P<ext>[a-z]+)$")


def update_manifest(mapping: dict[str, str]) -> None:
    """Keep manifest filenames in sync so provenance survives the rename."""
    path = REPORTS / "manifest.csv"
    if not path.exists() or not mapping:
        return
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)
    for r in rows:
        if r.get("filename") in mapping:
            r["filename"] = mapping[r["filename"]]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    cfg = load_config()
    names = class_names(cfg)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classes", nargs="*", default=names)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--renumber", action="store_true",
                    help="renumber every file from 001 instead of appending")
    ap.add_argument("--width", type=int, default=3, help="zero-pad width (default 3)")
    args = ap.parse_args()

    grand: dict[str, str] = {}
    for cls in args.classes:
        d = class_dir(cls)
        if not d.is_dir():
            print(f"  {cls:24s} (missing folder - run 00_scaffold.py)")
            continue

        files = list(iter_images(d))
        already, pending = [], []
        for f in files:
            m = FINAL.match(f.name)
            if m and m.group("cls") == cls and not args.renumber:
                already.append((int(m.group("num")), f))
            else:
                pending.append(f)

        next_n = (max((n for n, _ in already), default=0) + 1) if already else 1
        plan: list[tuple[Path, Path]] = []
        for f in sorted(pending, key=lambda p: p.name):
            ext = ".jpg" if f.suffix.lower() in (".jpeg", ".jpg") else f.suffix.lower()
            dest = d / f"{cls}_{next_n:0{args.width}d}{ext}"
            while dest.exists() and dest != f:
                next_n += 1
                dest = d / f"{cls}_{next_n:0{args.width}d}{ext}"
            plan.append((f, dest))
            next_n += 1

        for src, dest in plan:
            if src == dest:
                continue
            if not args.dry_run:
                src.rename(dest)
            grand[src.name] = dest.name

        print(f"  {cls:24s} {len(already):4d} already named, "
              f"{len(plan):4d} renamed  -> {len(files):4d} total")

    if not args.dry_run:
        update_manifest(grand)

    print(f"\nRenamed {len(grand)} files"
          f"{'  (DRY RUN - nothing changed)' if args.dry_run else ''}")
    print("Next:  python scripts/05_tally.py   then   python scripts/04_upload_roboflow.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
