#!/usr/bin/env python3
"""
Step 1 (quality gate): enforce the instruction doc's image standards.

Rejects (moved to quarantine/<class>/, never deleted):
  DUPLICATE     near-identical to an image already kept (perceptual hash)
  TOO_SMALL     below min resolution / megapixels
  BAD_ASPECT    extreme panorama or sliver
  STOCK         origin URL matches a watermarked-stock domain
  STAGED        origin URL suggests renovation / new build / before-after / how-to
  COLLAGE       looks like a side-by-side before/after composite
  NO_CONTEXT    likely a close-up crop with no visible building context

Nothing is auto-deleted: every rejection lands in quarantine with its reason
recorded in reports/qc_report.csv so borderline calls stay reviewable.

Usage:
  python scripts/02_qc_dedupe.py                # QC every class
  python scripts/02_qc_dedupe.py --classes roof_hole
  python scripts/02_qc_dedupe.py --dry-run      # report only, move nothing
  python scripts/02_qc_dedupe.py --no-context-check   # skip the crop heuristic
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (QUARANTINE, REPORTS, class_dir, class_names, ensure_dirs,
                    iter_images, load_config)

try:
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("Missing numpy/pillow.  Run:  pip install -r requirements.txt")


# --------------------------------------------------------------------------
# perceptual hash (DCT-based, 64-bit) - no external imagehash dependency
# --------------------------------------------------------------------------
def _dct2(a: np.ndarray) -> np.ndarray:
    n = a.shape[0]
    k = np.arange(n)
    basis = np.cos(np.pi * (2 * k[:, None] + 1) * k[None, :] / (2 * n))
    basis[:, 0] *= 1 / np.sqrt(2)
    return basis.T @ a @ basis


def phash(path: Path, size: int = 32, hash_size: int = 8) -> int | None:
    try:
        with Image.open(path) as im:
            g = im.convert("L").resize((size, size), Image.LANCZOS)
        arr = np.asarray(g, dtype=np.float64)
    except Exception:
        return None
    low = _dct2(arr)[:hash_size, :hash_size]
    med = np.median(low[1:].flatten() if low.size > 1 else low.flatten())
    bits = (low > med).flatten()
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------
# heuristics
# --------------------------------------------------------------------------
def looks_like_collage(path: Path) -> bool:
    """
    Detect staged before/after composites (two photos butted together).

    Tuned for PRECISION, not recall.  Measured on a fixture set: it catches
    composites that carry a visible divider bar, and misses roughly half of the
    seamless ones -- two photos butted together with no border share sky along
    the top and ground along the bottom, so the seam genuinely carries little
    signal.  That is accepted deliberately: a false positive silently deletes a
    good image, while a miss is still caught by the URL/query keyword filter
    (STAGED) and by the `review-staged` tag during annotation.  Measured false
    positive rate on normal house photos, including wide frames with a hard
    vertical edge at dead centre: 0%.

    All three tests below must agree before an image is rejected.
    """
    try:
        with Image.open(path) as im:
            w, h = im.size
            if h == 0 or w / h < 1.35:
                return False          # composites are essentially always wide
            arr = np.asarray(im.convert("RGB").resize((256, 256), Image.LANCZOS),
                             dtype=np.float32)
    except Exception:
        return False

    gray = arr.mean(axis=2)
    c = 128

    # 1. a jump present in almost EVERY row within a narrow central band
    #    (a band, not a single column, so a solid divider bar still registers)
    band = gray[:, c - 8:c + 9]
    if band.shape[1] < 3:
        return False
    row_jump = np.abs(np.diff(band, axis=1)).max(axis=1)
    if float((row_jump > 25).mean()) < 0.90:
        return False

    # 2. that jump must stand out against the rest of the image
    col_diff = np.abs(np.diff(gray, axis=1)).mean(axis=0)
    if float(np.abs(np.diff(band, axis=1)).mean()) < float(np.median(col_diff)) * 6:
        return False

    # 3. the two halves must genuinely be different scenes
    left, right = arr[:, :c], arr[:, c:]
    hl = np.histogram(left, bins=24, range=(0, 255))[0].astype(np.float32)
    hr = np.histogram(right, bins=24, range=(0, 255))[0].astype(np.float32)
    hl /= hl.sum() + 1e-6
    hr /= hr.sum() + 1e-6
    return float(np.abs(hl - hr).sum()) > 0.45


def looks_like_illustration(path: Path) -> bool:
    """
    Detect diagrams, CAD renders, clipart and infographics from pixels alone.

    The config's `diagram`/`clipart`/`vector` URL tokens only fire when the
    origin URL happens to say so.  A CAD render served from an inspection
    trade-body domain says nothing of the kind, so the call has to be made on
    the image.  Drawings differ from photographs in three ways at once: a large
    flat near-white background, a small palette, and mostly zero local
    gradient.

    All three must agree, the same precision-first posture as
    looks_like_collage.  A photograph with a blown-out overcast sky trips the
    white test alone; one of a plain painted wall trips the gradient test
    alone.  Neither trips all three.

    Thresholds are measured, not guessed.  On the fixture set below, the
    near-white fraction is what actually separates the two populations and it
    does so with a wide margin; the other two are guards against a white house
    under a blown-out sky:

        sample                 near-white  palette   flat
        CAD render (InterNACHI)     0.595      649  0.582
        photo, AI-generated         0.075     1816  0.461
        photo, boarded window       0.025     1560  0.277
        photo, peeling siding       0.016      416  0.381
        photo, close-up crop        0.000     1011  0.328

    Note the peeling-siding photo has a 416-colour palette -- smaller than the
    diagram's.  Palette size alone would reject it, which is why near-white
    carries the decision and palette only guards.
    """
    try:
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB").resize((256, 256), Image.LANCZOS),
                             dtype=np.uint8)
    except Exception:
        return False

    # 1. large near-white background/margin -- the dominant signal
    if float((rgb.min(axis=2) > 240).mean()) < 0.25:
        return False

    # 2. mostly flat: line art is uniform fill between hard edges
    g = rgb.mean(axis=2).astype(np.float32)
    if float((np.abs(np.diff(g, axis=1)) < 2.0).mean()) < 0.50:
        return False

    # 3. small palette (quantised to 5 bits per channel)
    q = (rgb >> 3).astype(np.uint32)
    codes = (q[:, :, 0] << 10) | (q[:, :, 1] << 5) | q[:, :, 2]
    return int(np.unique(codes).size) < 1200


def context_score(path: Path) -> float:
    """
    Proxy for "enough of the house is visible to draw a bounding box".

    A ground-level photograph of a house is a SCENE: it has a large flat bright
    sky/background band up top, and its content survives heavy downsampling
    because it is built from big regions (roof, wall, lawn).  A tight crop of
    shingles or peeling paint is a TEXTURE: no sky, and almost all of its
    variance lives in high frequencies that vanish when you shrink it.

    Returns ~0.0 (pure texture close-up) .. 1.0 (clear building scene).
    This is the fuzziest rule in the gate, so anything it flags is sent to
    quarantine for human review rather than discarded.
    """
    try:
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB").resize((320, 320), Image.LANCZOS),
                             dtype=np.float32)
    except Exception:
        return 1.0                      # never reject on a read error here

    gray = rgb.mean(axis=2)

    # (a) sky / open-background band -- needs flat AND bright together, so a
    #     dark flat crop and a bright noisy crop both score near zero.
    top_rgb, top = rgb[:96], gray[:96]
    flatness = float(np.exp(-float(top.std()) / 38.0))
    brightness = float(min(1.0, max(0.0, (float(top.mean()) - 55.0) / 145.0)))
    blueness = float(np.clip((top_rgb[:, :, 2] - top_rgb[:, :, 0]).mean() / 28.0,
                             0.0, 1.0))
    sky = float(np.clip(flatness * brightness * (1.0 + 0.35 * blueness), 0.0, 1.0))

    # (b) large-scale structure -- variance retained after a 16x16 downsample.
    #     Scene photos keep most of it; fine repetitive texture loses nearly all.
    total = float(gray.var())
    if total < 1e-6:
        return 0.0
    small = np.asarray(
        Image.fromarray(gray.astype(np.uint8)).resize((16, 16), Image.BOX),
        dtype=np.float32)
    structure = float(np.clip(small.var() / total, 0.0, 1.0))

    return round(float(np.clip(0.40 * sky + 0.60 * structure, 0.0, 1.0)), 3)


def url_flag(url: str, blocklist: list[str]) -> str | None:
    u = (url or "").lower()
    for token in blocklist:
        if token in u:
            return token
    return None


# --------------------------------------------------------------------------
def load_manifest_urls() -> dict[str, str]:
    path = REPORTS / "manifest.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row.get("filename", "")] = (row.get("source_url") or "") + " " + \
                                           (row.get("query") or "")
    return out


def main() -> int:
    cfg = load_config()
    std = cfg["standards"]
    names = class_names(cfg)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classes", nargs="*", default=names)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-context-check", action="store_true")
    ap.add_argument("--context-threshold", type=float, default=0.28,
                    help="below this context score -> NO_CONTEXT (default 0.28)")
    args = ap.parse_args()

    ensure_dirs(cfg)
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    urls = load_manifest_urls()

    report: list[dict] = []
    totals = {"kept": 0, "rejected": 0}
    reasons: dict[str, int] = {}

    for cls in args.classes:
        d = class_dir(cls)
        qdir = QUARANTINE / cls
        qdir.mkdir(parents=True, exist_ok=True)
        kept_hashes: list[tuple[int, str]] = []
        kept = rejected = 0

        for img in iter_images(d):
            reason = None
            detail = ""

            try:
                with Image.open(img) as im:
                    w, h = im.size
            except Exception:
                reason, detail = "UNREADABLE", "PIL could not open"
                w = h = 0

            meta = urls.get(img.name, "")

            if reason is None:
                if w < std["min_width"] or h < std["min_height"] or \
                        (w * h) / 1e6 < std["min_megapixels"]:
                    reason, detail = "TOO_SMALL", f"{w}x{h}"
                else:
                    ar = w / h if h else 0
                    if ar > std["max_aspect_ratio"] or ar < std["min_aspect_ratio"]:
                        reason, detail = "BAD_ASPECT", f"{ar:.2f}"

            if reason is None:
                t = url_flag(meta, std["stock_domain_blocklist"])
                if t:
                    reason, detail = "STOCK", t

            if reason is None:
                t = url_flag(meta, std["context_blocklist"])
                if t:
                    reason, detail = "STAGED", t

            if reason is None and looks_like_collage(img):
                reason, detail = "COLLAGE", "central seam + split histogram"

            if reason is None and looks_like_illustration(img):
                reason, detail = "ILLUSTRATION", "flat white bg + small palette"

            score = None
            if reason is None and not args.no_context_check:
                score = context_score(img)
                if score < args.context_threshold:
                    reason, detail = "NO_CONTEXT", f"score={score}"

            ph = phash(img)
            if reason is None and ph is not None:
                for kh, kn in kept_hashes:
                    dist = hamming(ph, kh)
                    if dist <= std["phash_hamming_threshold"]:
                        reason, detail = "DUPLICATE", f"d={dist} of {kn}"
                        break

            row = {"class": cls, "filename": img.name, "width": w, "height": h,
                   "context_score": score if score is not None else "",
                   "phash": f"{ph:016x}" if ph is not None else "",
                   "verdict": "REJECT" if reason else "KEEP",
                   "reason": reason or "", "detail": detail}
            report.append(row)

            if reason:
                rejected += 1
                reasons[reason] = reasons.get(reason, 0) + 1
                if not args.dry_run:
                    shutil.move(str(img), str(qdir / img.name))
            else:
                kept += 1
                if ph is not None:
                    kept_hashes.append((ph, img.name))

        totals["kept"] += kept
        totals["rejected"] += rejected
        print(f"  {cls:24s} kept {kept:4d}   rejected {rejected:4d}")

    out = REPORTS / "qc_report.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["class", "filename", "width", "height",
                                           "context_score", "phash", "verdict",
                                           "reason", "detail"])
        w.writeheader()
        w.writerows(report)

    print(f"\nKept {totals['kept']}   Rejected {totals['rejected']}"
          f"{'  (DRY RUN - nothing moved)' if args.dry_run else ''}")
    if reasons:
        print("Rejection breakdown:")
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {k:12s} {v}")
    print(f"\nReport    : {out}")
    print(f"Quarantine: {QUARANTINE}  (review before discarding)")
    print("Next:  python scripts/03_rename.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
