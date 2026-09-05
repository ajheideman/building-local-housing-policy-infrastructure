# Roboflow Universe Scan

Step 1 says *"You might also be able to find usable images on Roboflow. Look
around and see what's available."* Here is what is actually there, what it is
worth, and the catch that decides how much of it we can use.

---

## Headline finding

**No existing public dataset matches our seven-class taxonomy, and most of the
roof datasets are the wrong kind of picture entirely.**

Nearly every roof-damage dataset on Universe is built for **insurance and
inspection** work: drone-shot, aerial, or standing-on-the-roof close-ups of
shingle surfaces. Our instructions explicitly reject exactly that —
*"close-up crops with no visible building context (we need enough of the house
to eventually draw a bounding box)."* Our model has to work on **ground-level
street-facing views**, because the local half of this project is Street View
imagery.

So the roof datasets look far more relevant in a search-result list than they
turn out to be once you open them. Budget accordingly: **treat Universe as a
supplementary source, not a shortcut past the scraping.**

---

## Candidates worth opening

| Dataset | Classes | Images | License | Verdict |
|---|---|---:|---|---|
| [building-quality XN2K+MDJ 2](https://universe.roboflow.com/building-quality/building-quality-xn2k-mdj-2) | abandoned building, **damaged facade**, **damaged window**, illegal addition, illegal advertising, missing signboard, painting marks, **peeling facade finish**, stained marks, vacant store | ~2,000 | CC BY 4.0 | **Best match found.** Three classes map onto ours and the imagery is street-level with building context. Caveat: street-front/mixed-use stock, not US single-family — check the domain gap before leaning on it. |
| [Building defect on walls](https://universe.roboflow.com/builddef2/building-defect-on-walls) | crack, mold, **peeling_paint**, stairstep_crack, water_seepage | 472 | CC BY 4.0 | `peeling_paint` and `stairstep_crack` are directly relevant. Many frames are close-ups — filter hard on building context. |
| [Damaged Buildings](https://universe.roboflow.com/damaged-building-detection/damaged-buildings-vrcqx) | destroyed, major-damage, minor-damage, no-damage | 422 | CC BY 4.0 | Severity classes, not defect types — labels unusable for us. The `no-damage` images are a useful **candid** source for `no_repair`. |
| [Abandoned Buildings](https://universe.roboflow.com/maps-anyom/abandoned-buildings) | abandoned-buildings | 94 | CC BY 4.0 | Small, but abandoned structures are the densest source of boarded/broken windows. Re-label under `window_damage`. |
| [Roof Damage Detection](https://universe.roboflow.com/keyan/roof-damage-detection) | damage | 127 | CC BY 4.0 | Single generic class — too coarse. Usable as raw imagery only. |
| [Damaged Shingle Obj-Detection](https://universe.roboflow.com/shingle-roof-inspection/damaged-shingle-obj-detection) | Damaged, Not Damaged, Obvious Damage | 303 | CC BY 4.0 | Roof-surface close-ups. **Fails our context rule** — skip. |
| [Roof Damage (smartroof)](https://universe.roboflow.com/smartroof/roof-damage-ukqfw/dataset/1) | Puncture, Cracked Shingle, Hail Impact, Chipped Shingle, Degranulation, Dragons Tooth, Mechanical Damage | 47 | CC BY 4.0 | Granular shingle taxonomy, but tiny and macro-scale. **Skip.** |

Browse further from these class-search URLs:
[`class:roof`](https://universe.roboflow.com/search?q=class:roof) ·
[`class:facade`](https://universe.roboflow.com/search?q=class%3Afacade) ·
[`class:building`](https://universe.roboflow.com/search?q=class%3Abuilding) ·
[`class:peeling`](https://universe.roboflow.com/search?q=class:peeling+of+paint) ·
[`class:vacant`](https://universe.roboflow.com/search?q=class:vacant) ·
[`class:house`](https://universe.roboflow.com/search?q=class%3Ahouse)

---

## Gap analysis against our seven classes

| Our class | Universe coverage | Verdict |
|---|---|---|
| `exterior_wall_damage` | Partial — "damaged facade", crack/stairstep_crack | Scrape most of it |
| `window_damage` | Partial — "damaged window", abandoned buildings | Scrape most of it |
| `roof_hole` | Effectively none at street level | **Scrape all of it** |
| `facade_peeling_paint` | Good — two datasets label it explicitly | Universe can carry a real share |
| `missing_shingles` | Plenty, but wrong viewpoint (aerial/macro) | **Scrape all of it** |
| `sagging_roof` | None found | **Scrape all of it** |
| `no_repair` | Good — "no-damage" classes, house datasets | Universe helps, and helps *specifically* with the listing-photo bias problem |

---

## The practical recommendation

**Harvest images, re-annotate labels.** Every dataset above uses a different
taxonomy from ours, so no label transfers cleanly. What does transfer is the
imagery — and CC BY 4.0 permits reuse with attribution.

Workflow:

1. Download the dataset from Universe (any export format — we only want the
   `images/` directory).
2. Drop the images into the matching `dataset/<class>/` folder.
3. Run `scripts/02_qc_dedupe.py` — the context-score gate will automatically
   strip out the aerial and macro shots that fail our building-context rule,
   which is exactly the filter this source needs.
4. Run `scripts/03_rename.py`, then upload in the same `global` batch.
5. Annotate under **our** taxonomy using `docs/ANNOTATION_GUIDE.md`.

### Attribution

All seven datasets above are **CC BY 4.0**, which requires crediting the
creator. Keep a running `docs/ATTRIBUTIONS.md` listing every dataset used, its
creator, and its Universe URL — this matters for a federally-funded project and
is far easier to maintain as you go than to reconstruct later.

### One thing to confirm

The `global` tag applied in Step 3 covers *scraped* imagery generally. If any
Universe data is used, consider a second tag (`universe`) alongside it, so
Universe-sourced images can be ablated separately from search-scraped ones.
Different provenance, different failure modes — worth being able to tell apart.
