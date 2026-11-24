# FFW-SH5 retargeting

`arcade_retarget/ffw_sh5/solver.py` is the solver that produced the released FFW-SH5
trajectories, with the same algorithm and parameters. It reads a public ARCADE-Checkout-Human release
through `arcade_retarget/human_source.py`. `python -m arcade_retarget.ffw_sh5` runs it over
worker processes and then attaches the products (`arcade_retarget/ffw_sh5/object_track.py`).

## Inputs

From the ARCADE-Checkout-Human release, per episode:

* **Shopper motion:** shoulders, elbows and both hands (21 landmarks each).
* **Product:** pose trajectory, measured size and textured mesh. The mesh is turned into a
  signed distance field for clearance checks, cached on disk (`ARCADE_CACHE`, default
  `~/.cache/arcade_retarget/product_mesh`).
* **Carrying intervals per hand:** from `interaction/*/carrying`, the hand the product moves
  with. The first carrying start and the last carrying end bound the robot's window.
* **Counter extent:** shared by all episodes. It comes from
  `arcade_retarget/configs/counter_capture_20260818_01.json` (inferred from where products rest
  in the recording session), so a subset run gives the same result as a full run. Pass
  `--counter release` to recompute it from the release.

From the robot description (`retarget/robotis_ffw_sh5/fetch_robot.sh`):

* the FFW-SH5 URDF;
* the collision meshes of the HX5-D20 hand links.

## Steps

1. **Window.** The robot follows the shopper only inside one window shared by both hands, from
   `buf_pre` frames before the first grasp to `buf_post` frames after the last release.
   Outside it, the arms and fingers stay at a home pose.
2. **Hand retargeting.** For every frame in the window, the robot hand frame and its 20 finger
   joints are fitted to the human hand by least squares:
   * fingertip positions first, then phalanx and palm directions;
   * within the HX5-D20 joint limits;
   * without finger self-collision;
   * with frame-to-frame continuity (`fq_vmax` per step).
3. **Clearance.** Up to `fade_n` (6) frames before the first grasp and from `rel_n` (3) frames
   after the last release only the wrist path is shifted, with the hand shape unchanged, so the
   hand mesh clears the product and the counter; the shift fades out over the 6 frames before the
   grasp. From the first grasp to the last release it is zero. After the last release the hand
   also retreats from the product (`retreat`). The shift is stored as `<hand>__avoid`. These are
   the [phases](../../README.md#what-happens-in-an-episode) 0, 1 and 3 of each hand.
4. **Idle hand.** A hand that is not holding and is not about to grasp moves toward a rest
   pose beside the body when it comes within `yield_d1` of the working hand or arm
   (`<hand>__yield`).
5. **Whole-body IK** (Pink, QP solver `quadprog`). Variables: the planar swerve base and both
   7-DoF arms. Costs and constraints:
   * frame tasks on both hands;
   * elbow direction;
   * posture;
   * base regularisation;
   * joint and velocity limits;
   * spherical barriers around the torso, at the counter edge and between the hands.

   The base back-off is chosen from `dx_grid` by tracking error.
6. **Re-timing.** Stretches where the arm misses its target by more than `rt_tol` or would
   exceed its velocity limit are slowed down and solved again, for up to `retime_rounds`
   rounds. This produces the `tmap` time map.
7. **Home transitions.** Home ↔ window edge is a quintic joint-space transition that matches
   the velocity at the window edge. A transition that dips into the counter, the product or
   the other hand is pushed out; if it still collides, a wrist-space blended path is used
   instead. Near the working arm or its product, a hand at home moves to a park pose beside
   the body. The base follows slowly and returns to its start pose after the window.
8. **Finger refit and head.** From the final wrist poses, the fingers are fitted again to the
   human fingertips. The head aims the ZED camera at the working hand's fingertip.
9. **Product.** `object_track.py` moves the product onto the output steps. While carried it
   rides with the robot hand: the human hand–product relation, expressed in the planned hand
   frame, is carried to the reached hand frame (`obj_carrier` says which hand; a change of
   carrier is blended over `settle_n` steps). After a release it settles onto its nearest
   stable face.

Product contact is not modelled: from the first grasp to the last release the hands may touch
the product. The counter is always a barrier.

All parameters keep the values used for the released data. They are recorded in
`PREFIX_ik.json -> args`, and `python -m arcade_retarget.ffw_sh5.solver --help` lists them.

## Robot-side check

Every released episode passes an automatic check of the robot motion, computed with the
robot's collision meshes and the product mesh. An episode is left out when any of these hold:

| check | condition |
|---|---|
| finger self-collision | fingers of one hand interpenetrate by more than 3 mm for 3 or more consecutive steps |
| finger speed | a finger joint changes by more than 25° in one step |
| touch before the grasp | a hand is more than 5 mm inside the product for 3+ steps up to 6 frames before the episode's first grasp (phase 0) |
| touch after the release | a hand is more than 5 mm inside the product for 3+ steps from 3 frames after its last release |
| counter | a hand or wrist is more than 10 mm below the counter top for 3+ steps |
| hand overlap | the two hands overlap by more than 5 mm for 3+ steps |
| idle hand | the hand that never holds the product comes within 3 mm of the working hand or arm for 3+ steps |
| arm branch | an arm joint turns by more than 90° while the wrist barely moves |
| product in hand | the carried product is more than 30 mm from the robot hand mesh while it moves, for 3+ steps |
| product path | the carried product is more than 30 mm from the human product path for 5+ steps |

## Quality figures (94 episodes)

From the released files and the per-episode summary lines of `PREFIX_ik.log`:

| metric (per episode) | median | p90 | max |
|---|---|---|---|
| output steps | 190 | 240 | 304 |
| hand position error vs. planned target, p50 (mm) | 2.4 | 3.6 | 7.9 |
| hand position error, p90 (mm) | 8.3 | 12.7 | 140.2 |
| hand rotation error, p50 (deg) | 0.6 | 0.9 | 2.6 |
| hand rotation error, p90 (deg) | 2.2 | 3.9 | 42.8 |
| carried product, largest deviation from the human product path (mm) | 10.1 | 29.4 | 55.9 |
| finger self-penetration, largest (mm) | 1.0 | 2.2 | 3.6 |
| largest base translation (mm) | 167 | 214 | 349 |
| largest base yaw change (deg) | 7 | 27 | 64 |

| fingertip error after the refit, per hand (mm) | thumb | index | middle | ring | little |
|---|---|---|---|---|---|
| median | 6 | 9 | 4 | 7 | 22 |
| p90 | 8 | 15 | 6 | 11 | 27 |

The tracking errors compare the robot hand with the **planned** hand target on steps where it
follows the shopper (`<hand>__w = 1`). The planned target is the human hand frame, shifted by
`<hand>__avoid` before the first grasp and after the last release, and blended toward the rest
pose by `<hand>__yield`.

* **Joint limits:** none of the 253,666 arm-joint samples is beyond the URDF limits, and
  5.8 % are within 0.05 rad of a limit.
* **Contact while holding:** part of the hand is more than 5 mm inside the product mesh in
  34 % of the holding time (deepest point per hand: median 9 mm). The thumb, or both index and
  middle fingertips, are more than 1 cm off the surface in 5 % of it. The data is kinematic:
  a physics replay needs contact refinement to hold the product.
* **Speed:** 89 of 94 episodes were re-timed somewhere. While following the shopper the robot
  takes 1.22 steps per human frame (12,089 steps for 9,925 frames); the rest of the 18,119
  steps are the home transitions.

## Reproducibility

The released trajectories were computed by this solver, with the same parameters, from the
same 94 episodes before they were exported to ARCADE-Checkout-Human, which stores them at float32
precision. Re-running `python -m arcade_retarget.ffw_sh5` on the public ARCADE-Checkout-Human
release gives:

* **Determinism:** repeated runs are bit-identical, also with a different number of workers
  or another cache location (checked on two episodes).
* **Per episode:**
  * 58 of 94 episodes keep the same number of output steps. For these, the largest
    arm-joint difference per episode is ≤ 0.001 rad in 30 episodes, ≤ 0.05 rad in 41 and
    ≤ 0.2 rad in 54.
  * In the other 36 the re-timing differs: by at most 10 steps in 35 of them, and by 77 steps
    in `J06758_right`.
  * The solver makes discrete choices: base back-off, clearance rounds, re-timing and the
    form of the home transitions. Tiny input differences flip some of them, and the episode
    then settles into a different but equally valid solution.
* **Aggregate quality is unchanged:**

| median over episodes | released | re-run from the public release |
|---|---|---|
| hand position error p50 / p90 (mm) | 2.39 / 8.29 | 2.40 / 8.25 |
| hand rotation error p50 / p90 (deg) | 0.58 / 2.18 | 0.60 / 2.20 |
| arm-joint samples within 0.05 rad of a limit (%) | 5.81 | 5.81 |
| arm-joint samples beyond a limit | 0 | 0 |
| total output steps | 18,119 | 18,044 |

The [robot-side check](#robot-side-check) was applied to the released trajectories, so use
those when you need checked episodes.

`tests/test_retarget_sample.py::test_solver_reproduces_sample` re-solves `J03826_left` from
the ARCADE-Checkout-Human sample and requires agreement with the released trajectory within 0.05 rad.
The measured difference is 0.0004 rad.

## Runtime

The solver is CPU-only, about 2 min of CPU per episode, most of it in the per-frame hand fit.
All 94 episodes take 16 min on 12 worker processes (a 16-vCPU machine). `--workers`
sets the parallelism. The product distance fields are built once per product size and cached.
