# Prompt for browser-controlling Claude (Roboflow annotation)

Copy everything between the lines.

---

You are annotating a computer-vision training dataset in Roboflow. Work
carefully and accurately; this data trains a model used for housing policy
research, so a wrong box is worse than no box.

**Project:** https://app.roboflow.com/measuring-housing-repair-needs-study/housing-repair-need-detection
Open the project, go to **Annotate**, and open the batch tagged `global`
(1,169 images). Work through images in order.

## Task

For each image, draw a tight bounding box around **each visible defect** and
assign the matching class. One image may get several boxes, including boxes of
different classes. Use these seven class names EXACTLY as written:

exterior_wall_damage, window_damage, roof_hole, facade_peeling_paint,
missing_shingles, sagging_roof, no_repair

## What each class means

- **exterior_wall_damage** — missing or detached siding; missing, spalled or
  crumbling brick; failed/missing mortar; rotted or holed wood cladding;
  breached stucco.
  NOT: paint failure over intact cladding; dirt, staining or algae; hairline
  cosmetic cracks.

- **window_damage** — a window boarded with plywood/OSB/metal, or with broken,
  shattered, cracked or missing glazing.
  NOT: curtains, blinds, dark or reflective glass, intact security bars or
  shutters, missing insect screens. A doorway is not a window.

- **roof_hole** — an opening THROUGH the roof plane exposing decking, interior
  or sky.
  NOT: missing surface shingles with the deck intact; dark patches or shadow;
  skylights or vents.

- **facade_peeling_paint** — paint or coating peeling, flaking, blistering or
  chipping off a substrate that is still intact.
  NOT: fading or discoloration alone; cases where the substrate itself is
  missing or broken.

- **missing_shingles** — shingles or tiles absent from the roof surface with
  underlayment or decking exposed, the deck flat and unbroken.
  NOT: through-holes; deflection; moss, streaking or granule discoloration.

- **sagging_roof** — visible deflection of the roof plane or ridge: swayback,
  dip, bow, partial collapse.
  NOT: intentional architectural curves (catenary or eyebrow roofs, decorative
  thatch); camera lens distortion; sagging gutters.

- **no_repair** — a sound home with no visible defect. **Draw NO box.** Leave
  the image with zero annotations and mark it done. It is a negative example.

## Decision order — the roof classes

These three are the most confused. Check in this order and apply EVERY rule
that fires; they stack:

1. Is the roof plane deflected (ridge dips, surface bows, section collapsed)?
   -> sagging_roof
2. Is there an opening through the roof exposing interior/decking/sky?
   -> roof_hole
3. Are shingles absent but the deck beneath flat and unbroken?
   -> missing_shingles

A collapsed section usually earns BOTH sagging_roof and roof_hole. A
storm-stripped roof often earns missing_shingles plus roof_hole where the deck
is punctured. Draw each as its own box.

## Decision order — the wall classes

Is the cladding or substrate itself gone, broken, rotted or crumbling?
   -> exterior_wall_damage
Otherwise, is the substrate intact but its coating failing?
   -> facade_peeling_paint

Bare weathered wood with boards intact and no paint left is coating failure
-> facade_peeling_paint. Boards split or rotted -> exterior_wall_damage.

## Box rules

- Tight around the defect, not the whole house and not the whole roof.
- Box the DEFECT, not the surface it sits on. "Sagging roof" means box the
  deflected span, not the entire roof of a sound house.
- If the same defect type appears in several separate places, draw a separate
  box for each.
- Do not draw a box that covers most of the image. If the defect genuinely
  covers the whole frame, the image is a close-up and should be skipped
  (see below).

## When NOT to annotate — skip and flag instead

Add the tag `review-needed` and move on, drawing no boxes, if the image:

- is a close-up with no building context (you cannot see enough house to place
  the defect on a structure);
- is a diagram, illustration, infographic, or a multi-panel comparison strip;
- shows renovation in progress (ladders, drop cloths, scaffolding, stripped
  siding being replaced);
- is an interior photograph;
- is not a building at all;
- looks AI-generated (implausibly perfect, dreamlike, or inconsistent detail);
- carries a large text banner or company watermark across the image;
- shows a defect you genuinely cannot classify.

Do NOT guess when unsure. Flagging is the correct action; a wrong label is
more expensive than an unlabelled image.

## Pace and reporting

Work in batches of 25 images. After each batch, report:
- how many images you annotated, and the box count per class;
- how many you tagged `review-needed`, and why;
- any image where you were unsure, by filename.

Stop and ask if you find yourself flagging more than 10 of any 25, or if the
class definitions above do not fit what you are seeing.

---
