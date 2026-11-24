# How the data was produced

This page describes how the released data was created. **The generation pipeline itself, and
the models it runs, are not part of this repository.** This repository only reads, validates
and visualises the released data.

## Capture

* **Setting:** one self-checkout counter in a lab. A shopper picks products up from the
  counter, inspects them, sometimes hands them from one hand to the other, and puts them
  down.
* **Cameras:**
  * two side cameras (`left`, `right`), fisheye lenses;
  * one top-down camera (`top`);
  * one front camera (`front`), used for pose reconstruction only.
* **Frame rate:** about 19.94 fps, software-synchronised.
* **Calibration:** ChArUco board, camera intrinsics plus multi-view extrinsics.
* **Session:** `capture_20260818_01`, about 9 minutes of continuous recording.
  The 97 released episodes cover 7.2 minutes.

## 2-D labels (per camera, whole session)

1. **Hand-object interaction (HOI).** A fused HOI and segmentation detector runs on the
   `left`, `right` and `top` views. A hand is "holding" in a view when the detector links
   it to an object near the projected 3-D wrist. The fused label requires 2 of 3 views and
   uses hysteresis. Released as `interaction/*/hoi_holding`.
2. **Object segmentation and tracking.** Product instances are segmented per view and
   tracked through the session.
3. **Grasp and release events.** Rules on the object tracks (which hand an object moves with)
   and the HOI signal give grasp and release instants per hand. They were then reviewed.

## 3-D motion, episodes and products

1. **3-D body and hands.** 2-D whole-body keypoints (133 points) from all four views are
   triangulated with the rig calibration.
2. **Body fit.** A body skeleton with bone lengths fixed for the whole session is fitted to the
   triangulated joints, so limbs keep their length and do not jump. Joints the cameras did not
   see are filled from the fit and flagged `body/filled`. The body's wrist is the hand's root.
3. **Hand fit.** A hand rig (wrist pose plus 21 finger joint angles) is fitted to the 2-D hand
   keypoints as a sequence, short gaps are filled in joint-angle space (`gap_filled`), fingers
   are pushed off product surfaces, and the motion is smoothed. While both hands hold the
   product, a hand the cameras lost is attached to it (also flagged `gap_filled`).
4. **Episodes.** The session is cut into one episode per product handled, from the grasp/release
   events and per-hand holding intervals. Each episode gets a lead-in and a tail of context
   frames.
5. **Segmentation masks.** Per-episode object masks are associated across views into
   instances, and the instance that is the episode's product is identified per frame
   (`segmentation/*/instances.json`).
6. **Product recognition.** Each episode's product is matched against the 5-product
   catalogue from the product masks, using colour and image-embedding similarity. Released
   in the episode attribute `recognition`.
7. **Product 6-DoF.** Each episode is fitted as a whole, as a sequence of contact modes: in
   every frame the product either rests on the counter or is carried by one hand.
   * **Resting phase:** one pose for the whole phase, on a stable face of the product, chosen
     by the multi-view mask evidence of all its frames (`object/source` `rest_<k>`).
   * **Carried phase:** the product follows the palm of the carrying hand, with a hand-relative
     pose that changes only slowly, fitted to the masks (`held_<hand>`). While both hands hold
     it, it is kept between them.
   * **Grasp, release and hand-over instants:** near each labelled event, the frame where the
     hand touches the product and the masks agree best. These instants give
     `interaction/*/carrying` and `object/state`. `interaction/*/holding` keeps the labelled
     grasp-to-release intervals, so during a hand-over both hands hold but only one carries.
   * The agreement of the posed product with the masks is kept per frame as
     `object/mask_iou`.
8. **Quality check.** Every episode is checked with the same thresholds for physical
   plausibility and for agreement with the multi-view masks:
   * the product below the counter or floating, a resting product that moves, tilts or stands
     upside down;
   * the product leaving or slipping in the holding hand, hand jumps, a gap between hand and
     product at grasp and release;
   * the posed product disagreeing with its masks (overall, over runs of frames, while resting,
     and in its long-axis direction while held).

   The 97 released episodes pass all of these checks.
9. **Frame.** All of the above is expressed in the counter frame
   ([COORDINATES.md](COORDINATES.md)).

## Products

There are 5 retail products: three cylindrical bottles (`mesil`, `cha17`, `sangaria_oolong`)
and two boxes (`diget`, `pepero_white`). Meshes are approximate shapes reconstructed from
photos and scaled to measured dimensions. Mass and friction were not measured.

## Observed and derived values

Use the `valid`, `body/filled` and `gap_filled` flags to separate observed from derived body and hand
values, and `object/mask_iou` to judge each frame's product pose.

## Version

Release 1.0.0, processed 2026-11-10 (recorded in `meta/info.json -> provenance`).
