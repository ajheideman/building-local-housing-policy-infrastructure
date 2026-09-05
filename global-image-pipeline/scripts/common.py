"""Shared helpers for the global image collection pipeline."""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing pyyaml.  Run:  pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "classes.yaml"
DATASET = ROOT / "dataset"
REPORTS = ROOT / "reports"
QUARANTINE = ROOT / "quarantine"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def class_names(cfg: dict) -> list[str]:
    return [c["name"] for c in cfg["classes"]]


def class_dir(name: str) -> Path:
    return DATASET / name


def iter_images(directory: Path):
    """Yield image files in a directory, sorted, case-insensitive extension match."""
    if not directory.is_dir():
        return
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            yield p


def count_images(directory: Path) -> int:
    return sum(1 for _ in iter_images(directory))


def human(n: int) -> str:
    return f"{n:,}"


def bar(value: int, target: int, width: int = 24) -> str:
    """Simple ASCII progress bar for terminal reports."""
    if target <= 0:
        return " " * width
    filled = min(width, int(round(width * value / target)))
    return "#" * filled + "." * (width - filled)


def ensure_dirs(cfg: dict) -> None:
    DATASET.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    for name in class_names(cfg):
        class_dir(name).mkdir(parents=True, exist_ok=True)
