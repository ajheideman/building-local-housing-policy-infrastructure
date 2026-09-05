# Global Image Pipeline (Model 1)

Collection, quality control and Roboflow upload for the **global (scraped)**
training set, following *Global Images Instructions.docx*: collect → organize →
upload → annotate → track.

## Status

1,170 images collected and uploaded on 2026-09-05 as a single batch tagged
`global`. Roboflow holds 1,110 after its own server-side de-duplication.

| class | images |
|---|---|
| exterior_wall_damage | 170 |
| window_damage | 170 |
| roof_hole | 153 |
| facade_peeling_paint | 167 |
| missing_shingles | 170 |
| sagging_roof | 170 |
| no_repair | 170 |
| **total** | **1,170** |

All classes meet the 150 minimum. Annotation (Step 4) has not started.

## Relationship to `collect images/`

That directory holds the earlier collection scripts and targets five
categories: `roof_damage`, `facade_deterioration`, `structural_sagging`,
`window_damage`, `no_repair_needed`.

The instructions document specifies **seven** classes and states the names must
be used exactly as written in Roboflow. The mapping is not a rename: the single
`roof_damage` bucket is split three ways by defect type, because the model must
distinguish a breach from surface loss from structural deflection.

    roof_damage           -> roof_hole | missing_shingles | sagging_roof
    facade_deterioration  -> facade_peeling_paint | exterior_wall_damage
    structural_sagging    -> sagging_roof
    window_damage         -> window_damage
    no_repair_needed      -> no_repair

This pipeline implements the seven-class taxonomy, and the images now in
Roboflow use those names. It also drops the paid Azure Bing Search dependency
(`BING_API_KEY`) in favour of `icrawler`, which needs no key, and adds a
quality-control stage the earlier scripts did not have.

## Running it

    pip install -r requirements.txt
    python scripts/00_scaffold.py

    python scripts/01_collect.py --list-plan
    python scripts/01_collect.py --backend bing --per-keyword 30
    python scripts/01_collect.py --backend wikimedia --per-keyword 15 --classes no_repair

    python scripts/02_qc_dedupe.py
    python scripts/03_rename.py
    python scripts/05_tally.py

    export ROBOFLOW_API_KEY=... ROBOFLOW_WORKSPACE=... ROBOFLOW_PROJECT=...
    python scripts/04_upload_roboflow.py --dry-run
    python scripts/04_upload_roboflow.py

Re-run order after any new collection round is 01 → 02 → 03 → 05 → 04.
Credentials are read from the environment only; nothing is stored in the repo.

## Quality control

`02_qc_dedupe.py` implements the document's "skip images that…" list. Rejected
files move to `quarantine/`, never deleted, and every verdict is recorded in
`reports/qc_report.csv` with its reason.

| rule | check |
|---|---|
| duplicates / near-duplicates | 64-bit DCT perceptual hash, Hamming <= 6 |
| watermarked stock photos | stock-domain blocklist against the origin URL |
| renovation / before-after staging | URL keyword blocklist |
| diagrams, clipart, infographics | pixel test: near-white background + flat regions + small palette |
| close-ups with no building context | scene-vs-texture score |
| unusable files | minimum resolution, megapixels, aspect ratio |

On the 2,506-image candidate pool, 856 rejections were watermarked stock
imagery — a third of everything the search engines returned. Provenance matters
here: the stock and staging rules read the origin URL, so `01_collect.py`
records the real source URL for every file in `reports/manifest.csv`. That
manifest is also what makes a licensing review possible before publication.

## Known limitations

- **Roof-class confusion.** Keyword searches for the three roof classes return
  overlapping results; 12 images were found under two different roof classes at
  once. Folder placement is a starting point, not a label — in object detection
  the bounding box class is authoritative, so apply the decision order in
  `docs/ANNOTATION_GUIDE.md` (sagging_roof -> roof_hole -> missing_shingles).
- **Contractor watermarks.** Many genuine damage photos come from roofing
  company sites and carry a company logo. These are not stock-agency images, so
  the blocklist does not catch them.
- **`no_repair` domain shift.** Searches for sound houses return real-estate
  listing photography, while damage searches return candid snapshots. Training
  on that split teaches photo style rather than building condition. 92 of the
  170 `no_repair` images come from Wikimedia to counter this.
- **Class boundaries are unsettled.** Four decisions are marked `DECIDE` in the
  annotation guide and should be resolved before labelling scales.

## Layout

    scripts/    00 scaffold, 01 collect, 02 qc+dedupe, 03 rename,
                04 upload, 05 tally, common helpers
    config/     classes.yaml — 7 classes, 142 keywords, thresholds, blocklists
    docs/       annotation guide, attributions, Roboflow Universe scan
    reports/    manifest.csv (provenance), counts.csv, STATUS.md

Image directories (`dataset/`, `quarantine/`, `overflow/`) are generated
locally and excluded from version control.
