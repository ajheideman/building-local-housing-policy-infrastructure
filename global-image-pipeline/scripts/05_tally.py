#!/usr/bin/env python3
"""
Step 5: running tally of images collected (and, optionally, annotated) per class.

Prints a console table, and writes:
  reports/counts.csv           machine-readable per-class counts
  reports/STATUS.md            paste-ready status update for the project lead

Any class below the configured minimum is flagged so search terms can be
adjusted, exactly as Step 5 asks.

Usage:
  python scripts/05_tally.py
  python scripts/05_tally.py --roboflow      # also pull annotated counts
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (QUARANTINE, REPORTS, bar, class_dir, class_names,
                    count_images, load_config)


def roboflow_annotated() -> dict[str, int]:
    """Best-effort annotated-count pull.  Silently returns {} if unavailable."""
    try:
        from roboflow import Roboflow
    except ImportError:
        print("  (roboflow SDK not installed - skipping annotated counts)",
              file=sys.stderr)
        return {}
    key = os.environ.get("ROBOFLOW_API_KEY")
    ws = os.environ.get("ROBOFLOW_WORKSPACE")
    pr = os.environ.get("ROBOFLOW_PROJECT")
    if not all([key, ws, pr]):
        print("  (set ROBOFLOW_API_KEY / _WORKSPACE / _PROJECT for annotated counts)",
              file=sys.stderr)
        return {}
    try:
        project = Roboflow(api_key=key).workspace(ws).project(pr)
        info = project.get_version_information() or []
        if info:
            classes = (info[0].get("splits") or {})
            if classes:
                return {k: int(v) for k, v in classes.items()}
        return {}
    except Exception as exc:
        print(f"  (roboflow lookup failed: {exc})", file=sys.stderr)
        return {}


def main() -> int:
    cfg = load_config()
    proj = cfg["project"]
    target, minimum = proj["target_per_class"], proj["min_per_class"]
    names = class_names(cfg)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roboflow", action="store_true",
                    help="also query Roboflow for annotated counts")
    args = ap.parse_args()

    annotated = roboflow_annotated() if args.roboflow else {}
    REPORTS.mkdir(parents=True, exist_ok=True)

    rows, short = [], []
    tot_kept = tot_quar = 0
    for name in names:
        kept = count_images(class_dir(name))
        quar = count_images(QUARANTINE / name)
        gap = max(0, target - kept)
        status = "OK" if kept >= minimum else ("SHORT" if kept else "EMPTY")
        if status != "OK":
            short.append((name, kept, target - kept))
        rows.append({"class": name, "collected": kept, "target": target,
                     "gap_to_target": gap, "quarantined": quar,
                     "annotated": annotated.get(name, ""), "status": status})
        tot_kept += kept
        tot_quar += quar

    # ---- console ----------------------------------------------------------
    print()
    print(f"  GLOBAL IMAGE DATASET - COUNTS   ({dt.date.today().isoformat()})")
    print(f"  {'class':24s} {'kept':>5s} {'/':^3s}{'tgt':<5s} {'progress':<26s} "
          f"{'quar':>5s}  status")
    print("  " + "-" * 78)
    for r in rows:
        print(f"  {r['class']:24s} {r['collected']:5d} {'/':^3s}{r['target']:<5d} "
              f"[{bar(r['collected'], r['target'])}] {r['quarantined']:5d}  "
              f"{r['status']}")
    print("  " + "-" * 78)
    goal = target * len(names)
    print(f"  {'TOTAL':24s} {tot_kept:5d} {'/':^3s}{goal:<5d} "
          f"[{bar(tot_kept, goal)}] {tot_quar:5d}")
    print()
    if short:
        print("  NEEDS ATTENTION (below "
              f"{minimum}) - broaden or swap keywords in config/classes.yaml:")
        for name, kept, need in short:
            print(f"    - {name:24s} has {kept}, need {need} more")
    else:
        print(f"  All seven classes are at or above the {minimum}-image minimum.")
    print()

    # ---- counts.csv -------------------------------------------------------
    csv_path = REPORTS / "counts.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["class", "collected", "target",
                                           "gap_to_target", "quarantined",
                                           "annotated", "status"])
        w.writeheader()
        w.writerows(rows)

    # ---- STATUS.md --------------------------------------------------------
    md = [f"# Global Image Dataset - Status", "",
          f"_Updated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}_", "",
          f"**{tot_kept} of {goal}** images collected across 7 classes "
          f"({tot_kept / goal * 100:.0f}%).", "",
          "| Class | Collected | Target | Gap | Annotated | Status |",
          "|---|---:|---:|---:|---:|---|"]
    for r in rows:
        ann = r["annotated"] if r["annotated"] != "" else "--"
        md.append(f"| `{r['class']}` | {r['collected']} | {r['target']} | "
                  f"{r['gap_to_target']} | {ann} | {r['status']} |")
    md += ["", f"**Quarantined (QC-rejected, retained for review):** {tot_quar}", ""]
    if short:
        md.append("## Classes below minimum")
        md.append("")
        for name, kept, need in short:
            md.append(f"- `{name}` - {kept} collected, **{need} short**; "
                      f"needs additional keyword variations.")
    else:
        md.append(f"All classes meet the {minimum}-image minimum.")
    md.append("")
    (REPORTS / "STATUS.md").write_text("\n".join(md), encoding="utf-8")

    print(f"  Wrote {csv_path}")
    print(f"  Wrote {REPORTS / 'STATUS.md'}   <- paste this into your update")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
