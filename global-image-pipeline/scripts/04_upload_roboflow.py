#!/usr/bin/env python3
"""
Step 3: upload all seven class folders to Roboflow as ONE batch, tagged `global`.

Why one batch matters: the instructions distinguish these scraped/global images
from the local Street View images that come later.  Every image here goes up
with batch_name=<one shared name> and tag_names=["global"], so the two sources
stay separable in the Roboflow UI and in every future dataset version.

Credentials come from the environment (never hard-code a key):
  export ROBOFLOW_API_KEY=...          # Settings -> Roboflow API -> Private API Key
  export ROBOFLOW_WORKSPACE=...        # the URL slug of your workspace
  export ROBOFLOW_PROJECT=...          # the URL slug of your project

Usage:
  python scripts/04_upload_roboflow.py --dry-run     # verify counts, upload nothing
  python scripts/04_upload_roboflow.py
  python scripts/04_upload_roboflow.py --classes roof_hole      # top up one class

Safe to re-run: every successful upload is journalled to reports/uploaded.txt
and skipped next time, so an interrupted run resumes instead of duplicating.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPORTS, class_dir, class_names, iter_images, load_config

JOURNAL = REPORTS / "uploaded.txt"


def load_journal() -> set[str]:
    if not JOURNAL.exists():
        return set()
    return {ln.strip() for ln in JOURNAL.read_text(encoding="utf-8").splitlines()
            if ln.strip()}


def journal(key: str) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as fh:
        fh.write(key + "\n")


def main() -> int:
    cfg = load_config()
    proj = cfg["project"]
    names = class_names(cfg)
    tag = proj["batch_tag"]

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classes", nargs="*", default=names)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch-name", default=None,
                    help="shared batch name (default: global-scrape-YYYY-MM-DD)")
    ap.add_argument("--split", default="train", choices=["train", "valid", "test"],
                    help="Roboflow split for these images (default: train)")
    ap.add_argument("--tag", action="append", default=None,
                    help=f"extra tag(s); '{tag}' is always applied")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=0.10,
                    help="seconds between uploads (default 0.10)")
    args = ap.parse_args()

    batch = args.batch_name or f"global-scrape-{dt.date.today().isoformat()}"
    tags = [tag] + [t for t in (args.tag or []) if t != tag]

    # ---- inventory --------------------------------------------------------
    done = load_journal()
    plan: list[tuple[str, Path]] = []
    print(f"\n  Batch name : {batch}")
    print(f"  Tags       : {', '.join(tags)}")
    print(f"  Split      : {args.split}\n")
    print(f"  {'class':24s} {'files':>6s} {'new':>6s}")
    print("  " + "-" * 40)
    for cls in args.classes:
        files = list(iter_images(class_dir(cls)))
        new = [f for f in files if f"{cls}/{f.name}" not in done]
        plan.extend((cls, f) for f in new)
        print(f"  {cls:24s} {len(files):6d} {len(new):6d}")
    print("  " + "-" * 40)
    print(f"  {'TOTAL TO UPLOAD':24s} {'':6s} {len(plan):6d}\n")

    if args.dry_run:
        print("  DRY RUN - nothing uploaded.")
        print("  Re-run without --dry-run to perform the upload.\n")
        return 0
    if not plan:
        print("  Nothing new to upload.\n")
        return 0

    # ---- credentials ------------------------------------------------------
    key = os.environ.get("ROBOFLOW_API_KEY")
    ws = os.environ.get("ROBOFLOW_WORKSPACE")
    pid = os.environ.get("ROBOFLOW_PROJECT")
    missing = [n for n, v in (("ROBOFLOW_API_KEY", key),
                              ("ROBOFLOW_WORKSPACE", ws),
                              ("ROBOFLOW_PROJECT", pid)) if not v]
    if missing:
        print(f"  ERROR: missing environment variable(s): {', '.join(missing)}",
              file=sys.stderr)
        print("  Set them, then re-run.  Use --dry-run to check counts without keys.",
              file=sys.stderr)
        return 2

    try:
        from roboflow import Roboflow
    except ImportError:
        print("  ERROR: roboflow SDK not installed.  pip install roboflow",
              file=sys.stderr)
        return 2

    project = Roboflow(api_key=key).workspace(ws).project(pid)

    ok = fail = 0
    failures: list[str] = []
    total = len(plan)
    for i, (cls, path) in enumerate(plan, 1):
        try:
            project.single_upload(
                image_path=str(path),
                batch_name=batch,          # same for all 7 folders -> ONE batch
                tag_names=tags,            # -> tags the whole batch 'global'
                split=args.split,
                num_retry_uploads=args.retries,
            )
            journal(f"{cls}/{path.name}")
            ok += 1
        except Exception as exc:
            fail += 1
            failures.append(f"{cls}/{path.name}: {exc}")
        if i % 25 == 0 or i == total:
            print(f"  {i:5d}/{total}  ok={ok} fail={fail}", flush=True)
        time.sleep(args.sleep)

    print(f"\n  Uploaded {ok}, failed {fail}.")
    if failures:
        log = REPORTS / "upload_failures.txt"
        log.write_text("\n".join(failures), encoding="utf-8")
        print(f"  Failures written to {log} - re-run to retry just those.")
    print(f"\n  VERIFY IN ROBOFLOW: open the project, filter images by tag "
          f"'{tag}', and confirm the count matches {ok}.")
    print("  Then proceed to Step 4 (annotation) using docs/ANNOTATION_GUIDE.md.\n")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
