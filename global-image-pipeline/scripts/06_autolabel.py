#!/usr/bin/env python3
"""
Step 4 (draft): pre-draw bounding boxes with an open-vocabulary detector.

These are DRAFT annotations, not ground truth.  OWLv2 is trained to find
objects, and the six damage classes are *conditions* -- "peeling", "sagging",
"missing" -- which it is measurably worse at than nouns like "window".  Run
--preview first and look at the rendered boxes before trusting any of it.

no_repair gets no boxes by design: it is the negative class, uploaded to
Roboflow as a background example.

Usage:
  python scripts/06_autolabel.py --preview --limit 4      # render, inspect
  python scripts/06_autolabel.py --classes roof_hole      # write VOC XML
  python scripts/06_autolabel.py                          # all damage classes
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASET, REPORTS, class_dir, class_names, iter_images, load_config

MODEL_ID = "google/owlv2-base-patch16-ensemble"

# Prompts are phrased as things a detector can localise.  Several per class:
# the defect itself, plus the host surface, because a box on the right surface
# is a better starting point for correction than no box at all.
PROMPTS: dict[str, list[str]] = {
    "exterior_wall_damage": ["missing siding on a house wall", "damaged brick wall",
                             "hole in the exterior wall of a house"],
    "window_damage":        ["a boarded up window", "a broken window",
                             "a window covered with plywood"],
    "roof_hole":            ["a hole in a roof", "a collapsed section of roof"],
    "facade_peeling_paint": ["peeling paint on a wall", "flaking paint on wood siding"],
    "missing_shingles":     ["missing shingles on a roof", "damaged roof shingles"],
    "sagging_roof":         ["a sagging roof", "a bowed roof line"],
}


def load_model():
    import torch
    from transformers import Owlv2Processor, Owlv2ForObjectDetection
    torch.set_num_threads(max(1, (torch.get_num_threads() or 4)))
    proc = Owlv2Processor.from_pretrained(MODEL_ID)
    model = Owlv2ForObjectDetection.from_pretrained(MODEL_ID).eval()
    return proc, model


def detect(proc, model, path: Path, prompts: list[str], threshold: float):
    import torch
    from PIL import Image
    with Image.open(path) as im:
        img = im.convert("RGB")
        w, h = img.size
        inputs = proc(text=[prompts], images=img, return_tensors="pt",
                      padding=True, truncation=True)
        with torch.no_grad():
            out = model(**inputs)
        res = proc.post_process_grounded_object_detection(
            outputs=out, target_sizes=torch.tensor([[h, w]]), threshold=threshold)[0]
    boxes = []
    for score, box in zip(res["scores"].tolist(), res["boxes"].tolist()):
        x1, y1, x2, y2 = [max(0, v) for v in box]
        x2, y2 = min(x2, w), min(y2, h)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        boxes.append((score, (int(x1), int(y1), int(x2), int(y2))))
    boxes.sort(key=lambda b: -b[0])
    return boxes, (w, h)


def write_voc(path: Path, cls: str, size, boxes) -> Path:
    w, h = size
    ann = ET.Element("annotation")
    ET.SubElement(ann, "folder").text = cls
    ET.SubElement(ann, "filename").text = path.name
    sz = ET.SubElement(ann, "size")
    ET.SubElement(sz, "width").text = str(w)
    ET.SubElement(sz, "height").text = str(h)
    ET.SubElement(sz, "depth").text = "3"
    for _, (x1, y1, x2, y2) in boxes:
        obj = ET.SubElement(ann, "object")
        ET.SubElement(obj, "name").text = cls          # the Roboflow class name
        ET.SubElement(obj, "difficult").text = "0"
        bb = ET.SubElement(obj, "bndbox")
        for tag, val in (("xmin", x1), ("ymin", y1), ("xmax", x2), ("ymax", y2)):
            ET.SubElement(bb, tag).text = str(val)
    out = path.with_suffix(".xml")
    ET.ElementTree(ann).write(out, encoding="utf-8")
    return out


def render(path: Path, boxes, dest: Path) -> None:
    from PIL import Image, ImageDraw
    with Image.open(path) as im:
        img = im.convert("RGB")
        d = ImageDraw.Draw(img)
        for score, (x1, y1, x2, y2) in boxes:
            d.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=4)
            d.text((x1 + 5, max(0, y1 - 14)), f"{score:.2f}", fill=(255, 0, 0))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, quality=88)


def main() -> int:
    cfg = load_config()
    damage = [c for c in class_names(cfg) if c != "no_repair"]
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classes", nargs="*", default=damage)
    ap.add_argument("--threshold", type=float, default=0.12)
    ap.add_argument("--max-boxes", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="images per class")
    ap.add_argument("--preview", action="store_true",
                    help="render boxes to reports/preview/ instead of writing XML")
    args = ap.parse_args()

    proc, model = load_model()
    total = hits = 0
    for cls in args.classes:
        if cls == "no_repair":
            continue
        files = list(iter_images(class_dir(cls)))
        if args.limit:
            files = files[:args.limit]
        found = 0
        for p in files:
            boxes, size = detect(proc, model, p, PROMPTS[cls], args.threshold)
            boxes = boxes[:args.max_boxes]
            total += 1
            if boxes:
                found += 1; hits += 1
            if args.preview:
                render(p, boxes, REPORTS / "preview" / cls / p.name)
            else:
                write_voc(p, cls, size, boxes)
        print(f"  {cls:24s} {found:4d}/{len(files):4d} images got a box", flush=True)
    pct = 100 * hits / total if total else 0
    print(f"\n  {hits}/{total} images have at least one box ({pct:.0f}%)")
    if args.preview:
        print(f"  previews: {REPORTS/'preview'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
