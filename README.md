# Building Local Housing Policy Infrastructure

**A scalable method for measuring housing repair needs using multi-source
imagery and deep learning.** NGA pilot project.

---

## What this project is trying to do

Cities need to know which homes need repair. Today they find out by sending
inspectors door to door, or by waiting for residents to complain. Both are slow,
expensive, and miss the houses nobody reports.

This project tests a different approach: **teach a computer to spot housing
disrepair in ordinary photographs of houses.** If it works, a city could survey
an entire neighbourhood from imagery it already has, and direct repair money to
the blocks that need it most.


---

## How it works, in four steps

```
   1. COLLECT              2. LABEL               3. TRAIN            4. MEASURE
   ────────────            ────────────           ────────────        ────────────
   Gather photos     →     A person marks   →     The model      →    Run it across
   of houses in            each defect in         learns what         a real city's
   every condition         the photos             each defect         imagery
                                                  looks like
```

**Step 1 — Collect.** Two separate sets of photographs, for two different jobs.

**Step 2 — Label.** A person draws a box around each defect and names it. This
is how the computer learns: it is shown thousands of examples of "this is a
hole in a roof" until it can recognise one it has never seen.

**Step 3 — Train.** The model studies the labelled examples and builds its own
internal sense of what each defect looks like.

**Step 4 — Measure.** Point the trained model at a city's street imagery and it
produces counts: how many homes on each block show signs of disrepair.

---

## The two image sets, and why there are two

| | **Global set** (Model 1) | **Local set** (Model 2) |
|---|---|---|
| **Where the photos come from** | Public image search across the internet | Google Street View, St. Louis |
| **What they look like** | Close, clear, well-lit — someone photographed the damage on purpose | Distant, angled, sometimes blurry — a car drove past |
| **What it is for** | Teaching the model what each defect *is* | Teaching the model to find defects in *real survey conditions* |
| **Status** | ✅ Collected, uploaded, awaiting labelling | ⬜ Not started |

The global set is the textbook; the local set is the exam. A model trained only
on crisp close-ups will fail on Street View, because Street View looks nothing
like a roofing contractor's portfolio. Both are needed.

---

## The seven things the model looks for

Six kinds of damage, plus one category for houses in sound condition. The names
in `code font` are used exactly as written everywhere in the project.

| | What it means in plain terms |
|---|---|
| `exterior_wall_damage` | Siding or brick missing or broken — a hole in the wall of the house |
| `window_damage` | A window boarded over with plywood, or with broken or missing glass |
| `roof_hole` | An actual opening through the roof, where you can see inside or see sky |
| `facade_peeling_paint` | Paint flaking or peeling off. The wall underneath is fine; the paint is not |
| `missing_shingles` | Roof tiles gone, exposing the bare surface underneath. No hole through it |
| `sagging_roof` | The roof line dips or bows — a sign the structure underneath is failing |
| `no_repair` | A sound house with nothing visibly wrong. Just as important to teach |

**Why `no_repair` matters.** A model shown only damaged houses learns that every
house is damaged. It needs examples of sound houses to learn the difference.

**Why six categories and not one "damage" label.** A missing roof tile and a
collapsing roof are very different problems, costing very different amounts to
fix. A city allocating repair funds needs to tell them apart.

---

## Where things stand today

**5 September 2026**

| Stage | Status |
|---|---|
| Collect global images | ✅ Done — 1,148 photos |
| Sort into categories | ✅ Done |
| Upload to labelling tool | ✅ Done — all tagged `global` |
| **Label the images** | 🔜 **Next — needs a person** |
| Train the first model | ⬜ Waiting on labels |
| Collect Street View images | ⬜ Not started |

**Global image counts** — the target was roughly 150–170 per category:

| Category | Photos |
|---|---|
| `missing_shingles` | 170 |
| `no_repair` | 170 |
| `window_damage` | 168 |
| `exterior_wall_damage` | 166 |
| `facade_peeling_paint` | 164 |
| `sagging_roof` | 158 |
| `roof_hole` | 152 |
| **Total** | **1,148** |

Every category is above the 150 minimum.

---

## How the photos were chosen

Roughly 2,500 photographs were gathered and about half were thrown out. What got
rejected, and why:

| Rejected | Why it would hurt the model |
|---|---|
| **Stock photos** (856) | Carry visible watermarks. The model would learn to spot watermarks instead of damage — and almost none of the sound-house photos have one |
| **Before/after comparisons** | Two photos side by side. The model cannot tell which half it is meant to be learning from |
| **Diagrams and drawings** | Not photographs of real houses at all |
| **Extreme close-ups** | Zoomed so far in you cannot see the house, so there is nothing to point at |
| **Duplicates** | The same photo twice teaches nothing and skews the results |

Rejected photos are **moved aside, never deleted**, and every decision is
recorded with its reason, so any call can be reviewed and reversed.

**Every photo's original web address is recorded.** This is what makes it
possible to check image licensing before anything is published.

---

## What is in this repository

```
collect images/            Earlier collection scripts (R and Python),
                           including the Street View collector for Model 2

global-image-pipeline/     The global image pipeline — collection through upload
    README.md              Technical detail, how to run it
    scripts/               The seven processing steps
    config/                Category definitions and search terms
    docs/                  Labelling guide, image sources, credits
    reports/               Where every photo came from; current counts
```

Photographs themselves are **not** stored here. They live on the collection
machine and in Roboflow, the labelling tool. A thousand photographs would make
this repository unusably large, and their licensing varies by source.

---

## What happens next

**Labelling is the bottleneck, and it needs a person.** Roughly 1,148 photos
need boxes drawn around their defects. Software cannot do this reliably yet —
this was tested, and general-purpose vision models fail on it, because "sagging"
and "peeling" are conditions rather than objects. Asked to find a sagging roof,
they find a roof, and will happily mark a perfectly sound one.

The practical route is to label 150–200 photos by hand, train a first model on
those, and let it propose labels for the rest — which a person then corrects
rather than draws from scratch.

**Four definitions need settling before labelling starts.** Each one changes
what a correct label is, and changing them later means redoing the work:

1. **How bad is bad enough?** Does slightly faded paint count as needing repair,
   or only paint that is actually peeling off?
2. **Single-family homes only?** Do duplexes and small apartment buildings count?
3. **Do garages and sheds count?** If the shed roof has a hole but the house is
   fine, what is that?
4. **Only US housing?** Image searches return houses from the UK, Australia and
   elsewhere. Keep them for variety, or drop them since the pilot is St. Louis?

---

## Glossary

**Bounding box** — a rectangle drawn around something in a photo, to show the
computer where it is. Labelling means drawing these.

**Object detection** — the kind of model used here. It finds *where* something
is in a picture, not just whether it is present. Necessary because a house can
have several different defects in different places.

**Class** — one of the seven categories above.

**Training data** — the labelled photographs a model learns from. Its quality
sets a ceiling on how good the model can be: wrong labels teach wrong lessons.

**Roboflow** — the web tool where the photos are stored, labelled, and models
are trained.

**Model 1 / Model 2** — Model 1 learns from internet photos what damage looks
like. Model 2 applies that to Street View imagery of real streets.

**Quality control (QC)** — the automatic checks that discard unusable
photographs before anyone spends time labelling them.
