# Changelog

## 1.1.0

Processed 2026-11-25, from the same recording session (`capture_20260818_01`).

* **Every segmented episode is released, with its check.** 1.0.0 released only the 97 episodes that
  passed the quality check. 1.1.0 releases all 114 segmented episodes of the session and labels each
  one: 111 pass, 3 fail (`J06521_left`, `J06564_right`, `J06848_right`). 17,188 episode frames from
  8,969 unique session frames, 424 grasp/release events.
* **One human reconstruction for all robots.** In 1.0.0 the UR10e and G1 robot data had been
  computed from an earlier human reconstruction and intersected with the human release afterwards;
  from 1.1.0 all three robot datasets are built from this release.
* **Junction correction (new).** At every transition between resting and carried, and at every
  hand-over, a jump of the product relative to the palm (more than 4 cm or 20°) within 10 frames of
  the transition is removed by re-carrying those frames from the first settled frame; the resting
  pose is settled again on the nearest stable face.
* **Check scope (new).** The mask-agreement rules for the carried product are evaluated only where
  the cameras see it well: while it is carried at least 10 cm above the surface it was picked from
  and at least 8 frames away from grasp and release. Near the counter the hands and other products
  hide it. The physical rules apply everywhere. With the same recordings, 97 episodes passed in
  1.0.0 and 111 pass in 1.1.0.
* **Schema `arcade_human` 1.1.0.**
  * Episode attributes and `meta/episodes.jsonl` rows gain `check_passed` (bool) and `check_failed`
    (list of rule ids).
  * `meta/info.json` gains `n_episodes_passed`, `check_rules` (rule id → description), `counter`,
    `selection`, `not_included.rgb` and `not_included.camera_calibration`.
* **Package `arcade-human` 1.1.0.**
  * Reader: `Episode.check_passed`, `Episode.check_failed`, `ArcadeHuman.passed_ids`.
  * `time_split` uses the passing episodes and returns an extra list, `rejected`.
  * `arcade-human quality` reports the check and computes its figures over the passing episodes.
  * `arcade_human.render.CAPTURE_COUNTER` is set to the counter footprint of the release.
* **Counter.** One footprint for the human data and every robot: `x ∈ [-0.551, 0.057]`,
  `y ∈ [-0.840, 0.541]` (m, counter frame), a box around every resting product position of the
  session, recorded in `meta/info.json -> counter`.
* **Products de-identified.** The 5 products have public ids (`bottle_a`, `bottle_b`, `bottle_c`,
  `box_flat`, `box_long`). In the mesh textures, brand names, logos, codes and readable text are
  replaced by colour fields and unreadable glyphs; geometry, UVs and dimensions are unchanged.
* **RGB and calibration.** RGB video is not part of the release. For recordings whose participants
  consented to sharing, it can be provided on request, after consultation and de-identification.
  Camera intrinsics and extrinsics are not released.
* **Sample.** `samples/arcade_human_sample` has 4 episodes with their product masks:
  `J00601_right`, `J02562_right` and `J03826_left` pass the check; `J06564_right` fails it and is
  kept as an example.
* **Sizes.** Core (without masks) 41 MB. Masks for every episode are in the Hugging Face release.

## 1.0.0

First public release of ARCADE-Checkout-Human.

* 97 episodes from one recording session (`capture_20260818_01`) at a self-checkout counter:
  3-D body (23 joints) and hands (21 landmarks each), wrist frames, product 6-DoF poses with
  measured, textured product meshes, 360 grasp/release events, per-hand holding and carrying
  intervals, and product segmentation masks from the `left`, `right` and `top` cameras.
* Package `arcade-human`: reader, validator, quality summary, renderers and a rerun viewer.
  Schema `arcade_human` 1.0.0.
