#!/usr/bin/env python3
"""
Audit: does each image actually show the defect its folder claims?

Search engines return loosely-related results, so a folder is a hypothesis,
not a label.  CLIP scores each image against a short description of every
class plus several distractors ("an undamaged house", "a technical diagram"),
and reports where the assigned class is not the best match.

This does NOT relabel anything.  It writes reports/class_audit.csv so a human
reviews the disagreements, which is the cheap half of annotation.

  python scripts/07_class_audit.py --limit 5     # smoke test
  python scripts/07_class_audit.py               # all classes
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPORTS, class_dir, class_names, iter_images, load_config

MODEL_ID = "openai/clip-vit-base-patch32"

# One plain description per class, plus distractors.  The distractors matter:
# without them every image is forced into some damage class, and "an undamaged
# house" is exactly the competing hypothesis worth testing.
DESCRIPTIONS = {
    "exterior_wall_damage": "a house with missing siding or damaged broken brickwork",
    "window_damage":        "a house with a boarded up or broken window",
    "roof_hole":            "a house roof with a hole through it",
    "facade_peeling_paint": "a house wall with peeling flaking paint",
    "missing_shingles":     "a roof with shingles missing",
    "sagging_roof":         "a house with a visibly sagging drooping roof line",
    "no_repair":            "a well maintained house in good condition",
}
DISTRACTORS = {
    "_intact_house":     "a normal undamaged house in good repair",
    "_diagram":          "a technical diagram or illustration, not a photograph",
    "_interior":         "the inside of a room, an interior photograph",
    "_renovation":       "a house under construction or being repaired, with ladders and tools",
    "_not_a_building":   "something that is not a house or building",
}


def main() -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classes", nargs="*", default=class_names(cfg))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    proc = CLIPProcessor.from_pretrained(MODEL_ID)
    model = CLIPModel.from_pretrained(MODEL_ID, use_safetensors=True).eval()

    labels = list(DESCRIPTIONS) + list(DISTRACTORS)
    texts = [DESCRIPTIONS[k] for k in DESCRIPTIONS] + [DISTRACTORS[k] for k in DISTRACTORS]
    with torch.no_grad():
        tok = proc(text=texts, return_tensors="pt", padding=True)
        tfeat = model.get_text_features(**tok)
        tfeat = tfeat / tfeat.norm(dim=-1, keepdim=True)

    rows, agree, total = [], 0, 0
    for cls in args.classes:
        files = list(iter_images(class_dir(cls)))
        if args.limit:
            files = files[:args.limit]
        ok = 0
        for p in files:
            try:
                with Image.open(p) as im:
                    inp = proc(images=im.convert("RGB"), return_tensors="pt")
            except Exception:
                continue
            with torch.no_grad():
                ifeat = model.get_image_features(**inp)
                ifeat = ifeat / ifeat.norm(dim=-1, keepdim=True)
                sims = (ifeat @ tfeat.T).squeeze(0)
            best = int(sims.argmax())
            rows.append({"filename": p.name, "assigned": cls,
                         "best_match": labels[best],
                         "assigned_score": round(float(sims[labels.index(cls)]), 4),
                         "best_score": round(float(sims[best]), 4),
                         "agrees": labels[best] == cls})
            total += 1
            if labels[best] == cls:
                ok += 1; agree += 1
        pct = 100 * ok / len(files) if files else 0
        print(f"  {cls:24s} {ok:4d}/{len(files):4d} agree ({pct:3.0f}%)", flush=True)

    out = REPORTS / "class_audit.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])) if rows else None
        if w:
            w.writeheader(); w.writerows(rows)
    pct = 100 * agree / total if total else 0
    print(f"\n  {agree}/{total} images match their folder ({pct:.0f}%)")
    print(f"  Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
