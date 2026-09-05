#!/usr/bin/env python3
"""
Step 1: collect candidate images for each class from multiple public sources.

Backends
--------
  google     Google Images   (via icrawler; no API key)
  bing       Bing Images     (via icrawler; no API key)
  openverse  Openverse API   (Creative Commons; no key needed, higher limits with one)
  wikimedia  Wikimedia Commons API (public domain / CC)

Every downloaded file is recorded in reports/manifest.csv with its source,
query, and origin URL so provenance survives all the way to Roboflow.

Examples
--------
  python scripts/01_collect.py --backend bing --per-keyword 25
  python scripts/01_collect.py --backend all --classes roof_hole sagging_roof
  python scripts/01_collect.py --backend openverse --per-keyword 40 --classes no_repair
  python scripts/01_collect.py --list-plan          # show what WOULD be fetched
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, IMAGE_EXTS, REPORTS, class_dir, class_names,
                    count_images, ensure_dirs, iter_images, load_config)

USER_AGENT = "NGA-Housing-Policy-Research/1.0 (academic dataset collection)"


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------
def append_manifest(rows: list[dict]) -> None:
    if not rows:
        return
    path = REPORTS / "manifest.csv"
    header = ["filename", "class", "source", "query", "source_url",
              "width", "height", "phash", "collected_utc", "status", "notes"]
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def known_urls() -> set[str]:
    """URLs already collected, so re-runs don't re-download the same picture."""
    path = REPORTS / "manifest.csv"
    if not path.exists():
        return set()
    seen = set()
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            u = (row.get("source_url") or "").strip()
            if u:
                seen.add(u)
    return seen


def stage_name(cls: str, url: str, ext: str) -> str:
    """Temporary content-addressed name; 03_rename.py assigns final sequence."""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"_stage_{cls}_{h}{ext}"


def image_meta(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return 0, 0


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------
def _url_keeping_downloader():
    """
    icrawler downloader that preserves each image's origin URL.

    icrawler names downloaded files 000001.jpg, 000002.jpg ... and keeps no
    filename->URL mapping, so the origin URL is lost by the time the caller
    sees the files.  That silently disables every QC rule that inspects the
    URL (stock-domain and renovation/diagram blocklists) and makes the
    licensing review impossible, since nothing records where a file came from.

    Overriding get_filename fixes both: it is called once per download with the
    task dict, so it can name the file after the URL digest *and* record the
    mapping.  The record dict is returned alongside the class for the caller.
    """
    from icrawler.downloader import ImageDownloader

    recorded: dict[str, str] = {}

    class UrlKeepingDownloader(ImageDownloader):
        def get_filename(self, task, default_ext):
            url = task.get("file_url", "") or ""
            ext = Path(urlparse(url).path).suffix.lower()
            if ext not in IMAGE_EXTS:
                ext = f".{default_ext.lstrip('.')}" if default_ext else ".jpg"
            name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext
            recorded[name] = url
            return name

    return UrlKeepingDownloader, recorded


def collect_icrawler(engine: str, query: str, cls: str, n: int,
                     seen: set[str]) -> list[dict]:
    """Google / Bing image search via icrawler, preserving origin URLs."""
    try:
        if engine == "google":
            from icrawler.builtin import GoogleImageCrawler as Crawler
        else:
            from icrawler.builtin import BingImageCrawler as Crawler
    except ImportError:
        print(f"    ! icrawler not installed - skipping {engine}. "
              f"pip install icrawler", file=sys.stderr)
        return []

    downloader_cls, recorded = _url_keeping_downloader()

    rows: list[dict] = []
    dest = class_dir(cls)
    with tempfile.TemporaryDirectory() as tmp:
        crawler = Crawler(
            storage={"root_dir": tmp},
            downloader_cls=downloader_cls,
            downloader_threads=4,
            log_level=40,
        )
        try:
            crawler.crawl(keyword=query, max_num=n, min_size=(400, 300),
                          file_idx_offset=0)
        except Exception as exc:                       # network / parse failures
            print(f"    ! {engine} failed on '{query}': {exc}", file=sys.stderr)
            return []

        for f in sorted(Path(tmp).iterdir()):
            if f.suffix.lower() not in IMAGE_EXTS:
                continue
            # Real origin URL when the downloader recorded one; a content hash
            # only as a last resort, so dedupe still works if it did not.
            url = recorded.get(f.name)
            if not url:
                url = f"{engine}://{hashlib.sha1(f.read_bytes()).hexdigest()}"
            if url in seen:
                continue
            seen.add(url)
            out = dest / stage_name(cls, url, f.suffix.lower())
            shutil.copy2(f, out)
            w, h = image_meta(out)
            rows.append({"filename": out.name, "class": cls, "source": engine,
                         "query": query, "source_url": url, "width": w,
                         "height": h, "phash": "", "collected_utc": utcnow(),
                         "status": "raw", "notes": ""})
    return rows


def _download(url: str, dest: Path) -> bool:
    import requests
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT},
                         stream=True)
        if r.status_code != 200:
            return False
        ctype = r.headers.get("Content-Type", "")
        if "image" not in ctype:
            return False
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(65536):
                fh.write(chunk)
        return dest.stat().st_size > 8_000
    except Exception:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def collect_openverse(query: str, cls: str, n: int, seen: set[str]) -> list[dict]:
    """Openverse aggregates CC-licensed images from Flickr, Wikimedia, etc."""
    try:
        import requests
    except ImportError:
        print("    ! requests not installed - skipping openverse", file=sys.stderr)
        return []

    rows: list[dict] = []
    dest = class_dir(cls)
    page, got = 1, 0
    while got < n and page <= 5:
        try:
            r = requests.get(
                "https://api.openverse.org/v1/images/",
                params={"q": query, "page_size": min(50, n * 2), "page": page,
                        "mature": "false", "license_type": "all-cc"},
                headers={"User-Agent": USER_AGENT}, timeout=30)
            if r.status_code != 200:
                break
            results = r.json().get("results", [])
        except Exception as exc:
            print(f"    ! openverse failed on '{query}': {exc}", file=sys.stderr)
            break
        if not results:
            break
        for item in results:
            if got >= n:
                break
            url = item.get("url")
            if not url or url in seen:
                continue
            ext = Path(url.split("?")[0]).suffix.lower()
            if ext not in IMAGE_EXTS:
                ext = ".jpg"
            out = dest / stage_name(cls, url, ext)
            if not _download(url, out):
                continue
            seen.add(url)
            got += 1
            w, h = image_meta(out)
            rows.append({"filename": out.name, "class": cls, "source": "openverse",
                         "query": query, "source_url": url, "width": w, "height": h,
                         "phash": "", "collected_utc": utcnow(), "status": "raw",
                         "notes": item.get("license", "")})
            time.sleep(0.15)
        page += 1
    return rows


def collect_wikimedia(query: str, cls: str, n: int, seen: set[str]) -> list[dict]:
    """Wikimedia Commons free-media search."""
    try:
        import requests
    except ImportError:
        print("    ! requests not installed - skipping wikimedia", file=sys.stderr)
        return []

    rows: list[dict] = []
    dest = class_dir(cls)
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={"action": "query", "format": "json", "generator": "search",
                    "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": n,
                    "gsrnamespace": 6, "prop": "imageinfo",
                    "iiprop": "url|size", "iiurlwidth": 1280},
            headers={"User-Agent": USER_AGENT}, timeout=30)
        pages = r.json().get("query", {}).get("pages", {})
    except Exception as exc:
        print(f"    ! wikimedia failed on '{query}': {exc}", file=sys.stderr)
        return []

    for _, page in list(pages.items())[:n]:
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url or url in seen:
            continue
        ext = Path(url.split("?")[0]).suffix.lower()
        if ext not in IMAGE_EXTS:
            ext = ".jpg"
        out = dest / stage_name(cls, url, ext)
        if not _download(url, out):
            continue
        seen.add(url)
        w, h = image_meta(out)
        rows.append({"filename": out.name, "class": cls, "source": "wikimedia",
                     "query": query, "source_url": url, "width": w, "height": h,
                     "phash": "", "collected_utc": utcnow(), "status": "raw",
                     "notes": "commons"})
        time.sleep(0.15)
    return rows


BACKENDS = {
    "google":    lambda q, c, n, s: collect_icrawler("google", q, c, n, s),
    "bing":      lambda q, c, n, s: collect_icrawler("bing", q, c, n, s),
    "openverse": collect_openverse,
    "wikimedia": collect_wikimedia,
}


# --------------------------------------------------------------------------
def main() -> int:
    cfg = load_config()
    names = class_names(cfg)
    proj = cfg["project"]

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="bing",
                    choices=list(BACKENDS) + ["all"],
                    help="image source (default: bing)")
    ap.add_argument("--classes", nargs="*", default=names,
                    help="subset of class names (default: all seven)")
    ap.add_argument("--per-keyword", type=int, default=20,
                    help="images to request per keyword (default: 20)")
    ap.add_argument("--cap", type=int, default=None,
                    help="stop a class at this many files (default: max_per_class x2 "
                         "so QC has surplus to reject from)")
    ap.add_argument("--list-plan", action="store_true",
                    help="print the fetch plan and exit without downloading")
    args = ap.parse_args()

    unknown = [c for c in args.classes if c not in names]
    if unknown:
        ap.error(f"unknown class(es): {', '.join(unknown)}\nvalid: {', '.join(names)}")

    ensure_dirs(cfg)
    cap = args.cap or proj["max_per_class"] * 2
    backends = list(BACKENDS) if args.backend == "all" else [args.backend]
    by_name = {c["name"]: c for c in cfg["classes"]}

    if args.list_plan:
        total = 0
        print(f"Fetch plan  |  backends: {', '.join(backends)}  |  "
              f"{args.per_keyword}/keyword  |  cap {cap}/class\n")
        for cls in args.classes:
            kws = by_name[cls]["keywords"]
            n = len(kws) * args.per_keyword * len(backends)
            total += n
            print(f"  {cls:24s} {len(kws):2d} keywords  ->  up to {n:5,d} candidates")
        print(f"\n  {'TOTAL':24s}                 up to {total:5,d} candidates")
        print(f"  (QC in 02_qc_dedupe.py will cut this down to "
              f"{proj['target_per_class']}/class)")
        return 0

    seen = known_urls()
    grand = 0
    for cls in args.classes:
        have = count_images(class_dir(cls))
        print(f"\n=== {cls} ===  (have {have}, cap {cap})")
        if have >= cap:
            print("    already at cap - skipping")
            continue
        rows_all: list[dict] = []
        for kw in by_name[cls]["keywords"]:
            if have + len(rows_all) >= cap:
                break
            for be in backends:
                need = min(args.per_keyword, cap - have - len(rows_all))
                if need <= 0:
                    break
                print(f"    [{be:9s}] {kw!r} -> requesting {need}")
                rows = BACKENDS[be](kw, cls, need, seen)
                rows_all.extend(rows)
                print(f"                 got {len(rows)}")
        append_manifest(rows_all)
        grand += len(rows_all)
        print(f"    class total now: {count_images(class_dir(cls))}")

    print(f"\nCollected {grand} new files.")
    print("Next:  python scripts/02_qc_dedupe.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
