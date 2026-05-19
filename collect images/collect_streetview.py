"""
Google Street View Image Collector — St. Louis Housing Study
=============================================================
Pulls street-level images for residential parcels in St. Louis
using the Google Street View Static API.

Each parcel gets multiple images at different camera headings so
you capture the full building exterior, not just one face.

SETUP
-----
1. Install dependencies:
       pip install requests pandas pillow tqdm

   If your parcel data is a shapefile (not CSV):
       pip install geopandas

2. Get a Google Street View Static API key:
       https://console.cloud.google.com
       → Enable "Street View Static API"
       → Create an API key under Credentials
       Free: $200/month credit (~28,500 images free/month)
       After free tier: $7 per 1,000 images

3. Prepare your parcel data file (see PARCEL DATA section below).

4. Set your API key and file path at the top of the config section.

PARCEL DATA
-----------
Your parcel CSV/shapefile needs at minimum ONE of:
  Option A — lat/lng columns (best): "latitude", "longitude"
  Option B — address column: "address" (script will geocode it)

Recommended columns to also include:
  - parcel_id   (unique identifier — used for filenames)
  - prop_type   (to filter to single-family residential)

Where to get St. Louis parcel data:
  City:   https://www.stlouis-mo.gov/data/  (search "parcels")
  County: https://stlcountygis.maps.arcgis.com

OUTPUT
------
images/streetview/
    {parcel_id}/
        {parcel_id}_h0.jpg    ← facing the house head-on
        {parcel_id}_h45.jpg   ← 45° angle
        {parcel_id}_h315.jpg  ← 315° angle (opposite 45°)
        {parcel_id}_h90.jpg   ← side view (optional 4th shot)
"""

import os
import time
import hashlib
import requests
import pandas as pd
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

GOOGLE_API_KEY = "YOUR_GOOGLE_API_KEY_HERE"

# Path to your parcel data file (.csv or .shp)
PARCEL_FILE = "stl_parcels.csv"

# Column names in your parcel file — adjust to match your actual column headers
COL_PARCEL_ID  = "parcel_id"     # Unique parcel identifier
COL_LAT        = "latitude"      # Latitude  (leave blank if using address)
COL_LNG        = "longitude"     # Longitude (leave blank if using address)
COL_ADDRESS    = "address"       # Full street address (used if no lat/lng)
COL_PROP_TYPE  = "prop_type"     # Property type column (set to "" to skip filtering)

# Only keep rows matching these property type values (case-insensitive substring match)
# Set to [] to keep all parcels
RESIDENTIAL_TYPES = ["single family", "single-family", "residential", "sfr"]

# How many parcels to process (set to None for all)
# Start small (50–100) to test before running the full dataset
MAX_PARCELS = 100

# Camera headings (degrees from North) — 0=N, 90=E, 180=S, 270=W
# The script computes the heading pointing AT the house from the street.
# These offsets are applied relative to that computed heading.
# 3 images per parcel is a good balance of coverage vs. API cost.
HEADING_OFFSETS = [0, 45, -45]   # Add 90 for a 4th side-view shot

# Street View image parameters
IMG_WIDTH  = 640   # pixels (max 640 on free tier)
IMG_HEIGHT = 640
IMG_FOV    = 90    # field of view in degrees (60–90 works well for houses)
IMG_PITCH  = -5    # tilt down slightly to capture full building height

OUTPUT_DIR = Path("images/streetview")
REQUEST_DELAY = 0.3  # seconds between API calls

# ─── GEOCODING ────────────────────────────────────────────────────────────────

GEOCODE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"

def geocode_address(address: str) -> tuple[float, float] | None:
    """Convert a street address to (lat, lng). Returns None on failure."""
    params = {"address": address + ", St. Louis, MO", "key": GOOGLE_API_KEY}
    try:
        r = requests.get(GEOCODE_ENDPOINT, params=params, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            loc = results[0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"    Geocode error for '{address}': {e}")
    return None

# ─── STREET VIEW ──────────────────────────────────────────────────────────────

STREETVIEW_ENDPOINT = "https://maps.googleapis.com/maps/api/streetview"
METADATA_ENDPOINT   = "https://maps.googleapis.com/maps/api/streetview/metadata"

def check_streetview_availability(lat: float, lng: float) -> dict | None:
    """
    Check if Street View imagery exists near this location.
    Returns metadata dict if available, None if not.
    This is FREE — no charge for metadata requests.
    """
    params = {
        "location": f"{lat},{lng}",
        "radius": 50,           # Search within 50m of the parcel
        "key": GOOGLE_API_KEY,
        "source": "outdoor",    # Exclude indoor imagery
    }
    try:
        r = requests.get(METADATA_ENDPOINT, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "OK":
            return data
    except Exception:
        pass
    return None

def compute_heading(parcel_lat: float, parcel_lng: float,
                    camera_lat: float, camera_lng: float) -> float:
    """
    Compute the compass heading from the camera position pointing toward the parcel.
    This makes the camera face the house rather than a random direction.
    """
    import math
    d_lng = parcel_lng - camera_lng
    x = math.sin(math.radians(d_lng)) * math.cos(math.radians(parcel_lat))
    y = (math.cos(math.radians(camera_lat)) * math.sin(math.radians(parcel_lat)) -
         math.sin(math.radians(camera_lat)) * math.cos(math.radians(parcel_lat)) *
         math.cos(math.radians(d_lng)))
    heading = (math.degrees(math.atan2(x, y)) + 360) % 360
    return heading

def fetch_streetview_image(lat: float, lng: float, heading: float,
                           save_path: Path) -> bool:
    """Download a single Street View image. Returns True on success."""
    params = {
        "location": f"{lat},{lng}",
        "size": f"{IMG_WIDTH}x{IMG_HEIGHT}",
        "heading": round(heading, 1),
        "fov": IMG_FOV,
        "pitch": IMG_PITCH,
        "source": "outdoor",
        "key": GOOGLE_API_KEY,
    }
    try:
        r = requests.get(STREETVIEW_ENDPOINT, params=params, timeout=15)
        r.raise_for_status()

        # Google returns a grey "no imagery" placeholder image for missing locations.
        # Detect it by checking response size (placeholder is always ~5KB).
        if len(r.content) < 6000:
            return False

        if PIL_AVAILABLE:
            img = Image.open(BytesIO(r.content)).convert("RGB")
            img.save(save_path, "JPEG", quality=92)
        else:
            save_path.write_bytes(r.content)

        return True
    except Exception as e:
        print(f"    Image fetch error: {e}")
        return False

# ─── PARCEL LOADING ───────────────────────────────────────────────────────────

def load_parcels(filepath: str) -> pd.DataFrame:
    """Load parcel data from CSV or shapefile."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(
            f"Parcel file not found: {filepath}\n"
            "Download from:\n"
            "  City:   https://www.stlouis-mo.gov/data/\n"
            "  County: https://stlcountygis.maps.arcgis.com"
        )

    if path.suffix.lower() == ".shp":
        try:
            import geopandas as gpd
            gdf = gpd.read_file(filepath)
            # Extract centroid lat/lng from geometry if not already present
            if COL_LAT not in gdf.columns or COL_LNG not in gdf.columns:
                gdf = gdf.to_crs("EPSG:4326")
                gdf[COL_LAT] = gdf.geometry.centroid.y
                gdf[COL_LNG] = gdf.geometry.centroid.x
            return pd.DataFrame(gdf.drop(columns="geometry"))
        except ImportError:
            raise ImportError("Install geopandas to read shapefiles: pip install geopandas")
    else:
        return pd.read_csv(filepath, dtype={COL_PARCEL_ID: str})


def filter_residential(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only single-family residential parcels."""
    if not COL_PROP_TYPE or COL_PROP_TYPE not in df.columns or not RESIDENTIAL_TYPES:
        return df
    mask = df[COL_PROP_TYPE].astype(str).str.lower().str.contains(
        "|".join(RESIDENTIAL_TYPES), na=False
    )
    filtered = df[mask].copy()
    print(f"  Filtered to {len(filtered):,} residential parcels "
          f"(from {len(df):,} total)")
    return filtered

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Street View Image Collector — St. Louis Housing Study")
    print("=" * 60)

    if GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE":
        print("\nGoogle API key not set.")
        print("Get one at: https://console.cloud.google.com")
        print("Enable 'Street View Static API' and 'Geocoding API'.")
        return

    # Load and filter parcels
    print(f"\nLoading parcels from: {PARCEL_FILE}")
    try:
        df = load_parcels(PARCEL_FILE)
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        return

    df = filter_residential(df)

    if MAX_PARCELS:
        df = df.head(MAX_PARCELS)
        print(f"  Processing first {MAX_PARCELS} parcels (MAX_PARCELS limit)")

    print(f"  Total parcels to process: {len(df):,}")
    print(f"  Images per parcel: {len(HEADING_OFFSETS)}")
    print(f"  Estimated API calls: {len(df) * len(HEADING_OFFSETS):,}")
    print(f"  Estimated cost (after free tier): "
          f"${len(df) * len(HEADING_OFFSETS) / 1000 * 7:.2f}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    success_count = 0
    skip_count = 0
    fail_count = 0

    iterator = tqdm(df.iterrows(), total=len(df)) if TQDM_AVAILABLE else df.iterrows()

    for _, row in iterator:
        parcel_id = str(row.get(COL_PARCEL_ID, f"parcel_{_}"))
        parcel_dir = OUTPUT_DIR / parcel_id

        # Skip if already fully collected
        existing = list(parcel_dir.glob("*.jpg")) if parcel_dir.exists() else []
        if len(existing) >= len(HEADING_OFFSETS):
            skip_count += 1
            continue

        parcel_dir.mkdir(exist_ok=True)

        # Get coordinates
        lat, lng = None, None
        if COL_LAT in row and COL_LNG in row:
            try:
                lat, lng = float(row[COL_LAT]), float(row[COL_LNG])
            except (ValueError, TypeError):
                pass

        if lat is None and COL_ADDRESS in row:
            address = str(row[COL_ADDRESS])
            coords = geocode_address(address)
            if coords:
                lat, lng = coords
            time.sleep(REQUEST_DELAY)

        if lat is None or lng is None:
            fail_count += 1
            continue

        # Check if Street View imagery exists here (free metadata call)
        metadata = check_streetview_availability(lat, lng)
        if not metadata:
            fail_count += 1
            (parcel_dir / "NO_IMAGERY.txt").write_text(
                f"No Street View imagery within 50m of {lat},{lng}\n"
            )
            continue

        # Camera is at the Street View capture location; parcel is the target
        cam_lat = metadata["location"]["lat"]
        cam_lng = metadata["location"]["lng"]
        base_heading = compute_heading(lat, lng, cam_lat, cam_lng)

        # Download images at each heading offset
        saved = 0
        for offset in HEADING_OFFSETS:
            heading = (base_heading + offset) % 360
            label = f"h{int((base_heading + offset) % 360)}"
            save_path = parcel_dir / f"{parcel_id}_{label}.jpg"

            if save_path.exists():
                saved += 1
                continue

            ok = fetch_streetview_image(cam_lat, cam_lng, heading, save_path)
            if ok:
                saved += 1
            time.sleep(REQUEST_DELAY)

        if saved > 0:
            success_count += 1
        else:
            fail_count += 1

    # Summary
    print("\n" + "=" * 60)
    print("Done. Summary:")
    print(f"  Parcels with images:     {success_count:,}")
    print(f"  Parcels skipped (done):  {skip_count:,}")
    print(f"  Parcels failed/no image: {fail_count:,}")
    total_imgs = len(list(OUTPUT_DIR.rglob("*.jpg")))
    print(f"  Total images saved:      {total_imgs:,}")
    print(f"  Output folder:           {OUTPUT_DIR.resolve()}")
    print("\nNext steps:")
    print("  1. Spot-check ~20 parcels to confirm image quality")
    print("  2. Upload to RoboFlow for annotation")
    print("  3. Flag parcels with NO_IMAGERY.txt for manual review")
    print("=" * 60)


if __name__ == "__main__":
    main()
