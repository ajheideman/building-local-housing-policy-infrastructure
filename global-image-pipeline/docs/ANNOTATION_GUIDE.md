# Annotation Guide — Global Housing Repair-Need Dataset

**Project:** Building Local Housing Policy Infrastructure (NGA Pilot)
**Dataset:** Model 1 — global (scraped) training set
**Task:** object detection — a bounding box per defect, with the specific class

This guide exists because Step 4 of the instructions says to *flag* uncertain
cases rather than guess. Everything below is a proposed rule; the sections
marked **DECIDE** are the ones worth settling with the project lead before
annotation scales up, because changing them later means relabeling.

---

## 1. The seven classes

Use these strings **exactly** — they are the Roboflow class names.

| Class | Include | Exclude |
|---|---|---|
| `exterior_wall_damage` | Missing/detached siding; missing, spalled or crumbling bricks; missing or failed mortar (tuckpointing); rotted or holed wood cladding; breached stucco | Paint failure over intact cladding (→ `facade_peeling_paint`); dirt, staining, algae; hairline cosmetic cracks |
| `window_damage` | Window boarded with plywood/OSB/metal; broken, shattered, cracked or missing glazing | Curtains/blinds/shades; dark or reflective glass; intact security bars or shutters; missing screens only |
| `roof_hole` | An opening **through** the roof plane exposing decking, interior or sky | Missing surface shingles with intact deck (→ `missing_shingles`); dark patches or shadow; a skylight or vent |
| `facade_peeling_paint` | Paint or coating peeling, flaking, blistering or chipping off an intact substrate | Fading or discoloration alone; substrate itself missing or broken (→ `exterior_wall_damage`) |
| `missing_shingles` | Shingles/tiles absent from the roof surface, underlayment or decking exposed, deck intact and flat | Through-holes (→ `roof_hole`); deflection (→ `sagging_roof`); moss, streaking, granule discoloration |
| `sagging_roof` | Visible deflection of roof plane or ridge — swayback, dip, bow, partial collapse | Intentional architectural curves (catenary/eyebrow roofs); camera lens distortion; sagging **gutters** |
| `no_repair` | Sound single-family home, no visible defect from any class above | Any visible defect; non-residential; heavily obscured houses |

---

## 2. Decision order for the roof triad

`roof_hole`, `missing_shingles` and `sagging_roof` are the most-confused set.
Evaluate in this order, and **apply every rule that fires** — they stack:

```
1. Is the roof PLANE deflected — ridge dips, surface bows, section collapsed?
      -> sagging_roof            (structural failure)

2. Is there an OPENING through the roof exposing interior / decking / sky?
      -> roof_hole               (envelope breach)

3. Are shingles ABSENT but the deck beneath is flat and unbroken?
      -> missing_shingles        (surface-layer loss)
```

A collapsed roof section usually earns **both** `sagging_roof` and `roof_hole`.
A storm-stripped roof commonly earns `missing_shingles` plus, where the deck is
punctured, `roof_hole`. Draw each as its own box.

## 3. Decision order for the wall pair

```
Is the CLADDING or SUBSTRATE itself gone, broken, rotted or crumbling?
      -> exterior_wall_damage
Otherwise, is the substrate intact but its COATING failing?
      -> facade_peeling_paint
```

Edge case worth naming: **bare weathered wood.** Boards intact with no paint
left is coating failure → `facade_peeling_paint`. Boards split, rotted or
missing → `exterior_wall_damage`. If both are present, both boxes.

**DECIDE:** whether fully bare, silvered wood with *no* peeling still counts as
`facade_peeling_paint` or as `no_repair`. Current rule: it counts, because the
repair need (repaint) is real. Flag these for the lead's call.

---

## 4. How to draw the box

- **Tight around the defect**, not around the house. A box that encloses the
  whole home teaches the model "house = damage" and destroys precision.
- **One box per contiguous affected region**, not per shingle or per flake.
  Forty shingles missing from one patch is **one** box. Two separate bald
  patches on opposite roof slopes are **two** boxes.
- **Include a thin margin** (roughly 5%) of intact surrounding material so the
  model learns the boundary between sound and damaged.
- **Do not box across occlusions.** If a tree splits a peeling-paint wall into
  two visible parts, draw two boxes.
- **Minimum size:** skip anything under ~20 px on its shortest side or under
  ~1% of image area. Too small to learn from; flag the image instead.
- **Multiple classes per image is expected and good.** A house with peeling
  paint and a boarded window gets one box of each class.

---

## 5. `no_repair` — the negative class

`no_repair` images get **zero bounding boxes**. In Roboflow they are saved as
*null* / background examples.

This is not a formality: null examples are what stop the model from firing on
every shadow, dark shingle and reflective window. Roboflow will prompt you to
confirm an image has no annotations — confirm rather than skip, otherwise the
image never enters the training set.

> **Watch this closely — the biggest quality risk in the whole dataset.**
> `no_repair` searches return real-estate listing photos: professionally shot,
> golden hour, wide angle, staged landscaping. The six damage classes return
> candid phone snapshots, insurance-claim photos and news images. If that split
> holds, the model learns *photo quality* instead of *building condition*, and
> it will collapse the moment it meets Street View imagery — which looks like
> neither.
>
> Mitigation: source a substantial share of `no_repair` from candid,
> non-listing imagery — Wikimedia Commons street photography, Openverse,
> geotagged street scenes — and deliberately keep overcast, off-angle, and
> partially-occluded sound houses. The `openverse` and `wikimedia` backends in
> `01_collect.py` exist mainly for this.

---

## 6. Flagging protocol

Do not guess. In Roboflow, add the tag `review-needed` plus one reason tag:

| Tag | Use when |
|---|---|
| `review-severity` | Wear that may not rise to "needs repair" — light chalking, one curled shingle, minor mortar erosion |
| `review-class` | The defect is real but sits between two classes |
| `review-subject` | Not clearly single-family — duplex, rowhouse, apartment, mobile home, barn, shed, garage, commercial |
| `review-context` | Aerial/drone/interior/extreme-angle view, or not enough building visible to place a box |
| `review-staged` | Possible renovation-in-progress, demolition, new construction, or before/after composite |

Review flagged images in batches with the project lead rather than one at a
time — the point is to settle the *rule*, then apply it to every case at once.

**DECIDE — the four thresholds most likely to cause disagreement:**

1. **Severity floor.** Where does weathering become repair need? Proposal:
   the defect must be identifiable at a glance from the street at normal
   viewing distance.
2. **Building scope.** Single-family only, or include duplexes and small
   multifamily? The local Street View set will determine what the model
   actually meets in deployment — worth matching now.
3. **Detached structures.** Do garages, sheds and porches count as part of the
   home? Proposal: attached structures yes, freestanding no.
4. **Non-US housing stock.** Scraped results include international housing with
   different materials and roof forms. Proposal: keep it — it improves
   generalization — but tag `intl` so it can be ablated later.

---

## 7. Auto-annotation workflow

Step 4 anticipates using Roboflow's automated labeling. The sequence that
actually works:

1. **Hand-label a seed set: ~40–60 images per class**, drawn across the full
   range of angle and severity. Auto-annotation trained on easy examples only
   will propose easy examples only.
2. Train a quick model version on the seed set, or use **Label Assist** with it.
3. Run it over the remaining images to generate **proposals**.
4. **Review every proposal.** Correct the box, fix the class, delete false
   positives. Treat proposals as drafts, never as labels.
5. Retrain and repeat. Two or three rounds usually converges.

Track which images were hand-labeled versus model-proposed (a `seed` tag on the
first pass does it). If detection quality later looks suspect, you need to know
whether the labels or the model are at fault.

---

## 8. Consistency check before scaling

Before annotating all ~1,100 images, have two people independently label the
**same 50 images** and compare: same class, and box IoU above 0.5. Disagreement
above roughly 10% means the class definitions above still need tightening —
fix them then, not after a thousand boxes exist.

---

## 9. Quick reference

```
roof deflected ................ sagging_roof
opening through roof .......... roof_hole
shingles gone, deck intact .... missing_shingles
cladding gone/broken .......... exterior_wall_damage
coating peeling, wall intact .. facade_peeling_paint
window boarded or broken ...... window_damage
nothing wrong ................. no_repair   (zero boxes)
unsure ........................ tag review-needed + a reason
```
