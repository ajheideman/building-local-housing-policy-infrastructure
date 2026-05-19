"""
Housing Repair Image Collector
================================
Collects global training images for housing condition classification.

Two sources:
  1. Bing Image Search API  — reliable, free tier covers ~1,000 images/month
  2. RoboFlow Universe API  — check for existing labeled datasets first

SETUP
-----
1. Install dependencies:
       pip install requests pillow tqdm

2. Get a free Bing Search API key:
       https://portal.azure.com → Create resource → "Bing Search v7"
       Free tier: 1,000 transactions/month (plenty for this project)

3. (Optional) Get a RoboFlow API key:
       https://app.roboflow.com → Settings → API Keys
       Free account is sufficient.

4. Set your keys at the top of this file (or use environment variables).

USAGE
-----
    python collect_images.py

Output folder structure:
    images/
        roof_damage/
            roof_damage_001.jpg
            roof_damage_002.jpg
            ...
        facade_deterioration/
        structural_sagging/
        window_damage/
        no_repair_needed/   ← negative examples, equally important!
"""

import os
import time
import hashlib
import requests
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: Pillow not installed. Image validation will be skipped.")
    print("Install with: pip install Pillow\n")

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

BING_API_KEY = "YOUR_BING_API_KEY_HERE"   # Replace with your key
ROBOFLOW_API_KEY = ""                      # Optional — leave blank to skip

OUTPUT_DIR = Path("images")
IMAGES_PER_CATEGORY = 200   # 200 × 5 categories = 1,000 total
MIN_IMAGE_SIZE = (200, 200) # Discard images smaller than this (pixels)
REQUEST_DELAY = 0.5         # Seconds between API calls (be polite)

# Search queries per category.
# Multiple queries per category increases variety — Bing returns max 150/query.
CATEGORIES = {
    "roof_damage": [
        "residential roof damage missing shingles",
        "house roof deterioration sagging",
        "damaged roof residential home exterior",
    ],
    "facade_deterioration": [
        "house exterior paint peeling deterioration",
        "residential building facade crumbling bricks",
        "home siding damage rotting wood exterior",
    ],
    "structural_sagging": [
        "house structural sagging porch deterioration",
        "residential home foundation problems exterior visible",
        "sagging roof line house exterior",
    ],
    "window_damage": [
        "broken windows boarded up house",
        "residential window deterioration damaged frame",
        "house window damage repair needed exterior",
    ],
    "no_repair_needed": [
        # Negative examples are critical for a balanced model
        "well maintained residential house exterior",
        "good condition single family home",
        "new house exterior well kept",
    ],
}

# ─── BING IMAGE SEARCH ────────────────────────────────────────────────────────

BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/images/search"

def search_bing(query: str, count: int = 50, offset: int = 0) -> list[dict]:
    """
    Search Bing for images. Returns list of image result dicts.
    count: max 150 per call (Bing API limit).
    """
    headers = {"Ocp-Apim-Subscription-Key": BING_API_KEY}
    params = {
        "q": query,
        "count": min(count, 150),
        "offset": offset,
        "imageType": "Photo",
        "safeSearch": "Moderate",
        "aspect": "Square",        # Prefer square-ish images (better for CNN input)
    }
    try:
        response = requests.get(BING_ENDPOINT, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("value", [])
    except requests.exceptions.RequestException as e:
        print(f"  Bing API error: {e}")
        return []


def download_image(url: str, save_path: Path, min_size: tuple) -> bool:
    """
    Download and validate a single image. Returns True if saved successfully.
    Skips images that are too small, not valid images, or duplicates.
    """
    try:
        response = requests.get(url, timeout=8, stream=True)
        response.raise_for_status()

        raw = response.content

        # Deduplicate by MD5 hash of raw bytes
        img_hash = hashlib.md5(raw).hexdigest()
        hash_file = save_path.parent / ".hashes"
        existing = set()
        if hash_file.exists():
            existing = set(hash_file.read_text().splitlines())
        if img_hash in existing:
            return False  # Duplicate

        if PIL_AVAILABLE:
            try:
                img = Image.open(BytesIO(raw)).convert("RGB")
                if img.size[0] < min_size[0] or img.size[1] < min_size[1]:
                    return False  # Too small
                img.save(save_path, "JPEG", quality=90)
            except Exception:
                return False  # Not a valid image
        else:
            # Save raw bytes without validation
            save_path.write_bytes(raw)

        # Record hash to prevent duplicates on future runs
        with open(hash_file, "a") as f:
            f.write(img_hash + "\n")

        return True

    except Exception:
        return False


def collect_bing_images(category: str, queries: list[str], target: int, out_dir: Path):
    """Collect up to `target` images for a category using Bing."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Count images already collected (supports resuming)
    existing = len(list(out_dir.glob("*.jpg")))
    needed = target - existing
    if needed <= 0:
        print(f"  {category}: already have {existing} images, skipping.")
        return

    print(f"  {category}: have {existing}, need {needed} more.")
    collected = 0
    counter = existing + 1

    for query in queries:
        if collected >= needed:
            break

        per_query = (needed - collected) // max(1, len(queries) - queries.index(query))
        offset = 0

        while collected < needed and offset < 300:
            batch = search_bing(query, count=min(50, needed - collected), offset=offset)
            if not batch:
                break

            iterator = tqdm(batch, desc=f"    '{query[:40]}'") if TQDM_AVAILABLE else batch
            for result in iterator:
                if collected >= needed:
                    break
                url = result.get("contentUrl", "")
                if not url:
                    continue
                fname = out_dir / f"{category}_{counter:04d}.jpg"
                if download_image(url, fname, MIN_IMAGE_SIZE):
                    collected += 1
                    counter += 1
                time.sleep(REQUEST_DELAY)

            offset += 50

    total = len(list(out_dir.glob("*.jpg")))
    print(f"  {category}: done. Total images: {total}")


# ─── ROBOFLOW UNIVERSE SEARCH ─────────────────────────────────────────────────

def search_roboflow_universe():
    """
    Print available housing-condition datasets on RoboFlow Universe.
    These may save you annotation time in Phase 2 — many are pre-labeled.
    """
    if not ROBOFLOW_API_KEY:
        print("\nRoboFlow API key not set — skipping Universe search.")
        print("To search, add your key to ROBOFLOW_API_KEY at the top of this file.")
        print("Find datasets manually at: https://universe.roboflow.com")
        print("Suggested searches: 'roof damage', 'building damage', 'house condition'\n")
        return

    print("\nSearching RoboFlow Universe for existing housing datasets...")
    search_terms = ["roof damage", "building damage", "house exterior", "housing condition"]
    endpoint = "https://api.roboflow.com/dataset/search"

    for term in search_terms:
        try:
            params = {"api_key": ROBOFLOW_API_KEY, "q": term, "type": "image"}
            r = requests.get(endpoint, params=params, timeout=10)
            r.raise_for_status()
            results = r.json().get("datasets", [])
            if results:
                print(f"\n  Results for '{term}':")
                for ds in results[:3]:
                    name = ds.get("name", "Unknown")
                    imgs = ds.get("images", "?")
                    url = ds.get("url", "")
                    print(f"    • {name} ({imgs} images) — {url}")
        except Exception as e:
            print(f"  RoboFlow search error for '{term}': {e}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Housing Repair Image Collector")
    print("=" * 60)

    # Step 1: Check RoboFlow Universe for existing datasets
    search_roboflow_universe()

    # Step 2: Collect images via Bing
    if BING_API_KEY == "YOUR_BING_API_KEY_HERE":
        print("\nBing API key not set.")
        print("Get a free key at: https://portal.azure.com")
        print("Then replace YOUR_BING_API_KEY_HERE at the top of this file.\n")
        return

    print(f"\nCollecting images via Bing Image Search API")
    print(f"Target: {IMAGES_PER_CATEGORY} images per category")
    print(f"Output: {OUTPUT_DIR.resolve()}\n")

    OUTPUT_DIR.mkdir(exist_ok=True)

    for category, queries in CATEGORIES.items():
        print(f"\n[{category}]")
        collect_bing_images(
            category=category,
            queries=queries,
            target=IMAGES_PER_CATEGORY,
            out_dir=OUTPUT_DIR / category,
        )

    # Summary
    print("\n" + "=" * 60)
    print("Collection complete. Summary:")
    total = 0
    for category in CATEGORIES:
        count = len(list((OUTPUT_DIR / category).glob("*.jpg")))
        total += count
        status = "✓" if count >= IMAGES_PER_CATEGORY else f"⚠ only {count}"
        print(f"  {category:<25} {status}")
    print(f"\n  Total images collected: {total}")
    print(f"  Saved to: {OUTPUT_DIR.resolve()}")
    print("\nNext step: Upload these to RoboFlow for annotation (Phase 2).")
    print("=" * 60)


if __name__ == "__main__":
    main()
