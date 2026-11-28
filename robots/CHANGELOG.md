# Changelog

## 1.1.0

Processed 2026-11-25. All three robot datasets are rebuilt from ARCADE-Checkout-Human 1.1.0.

* **One human reconstruction for all robots.** In 1.0.0 the UR10e and G1 data had been computed
  from an earlier human reconstruction and intersected with the human release afterwards; 1.1.0
  builds all three robots from the same human release: the same episodes, hand and product poses,
  holding labels and counter. The raw outputs record it (`PREFIX_ik.json -> release`).
* **Every episode is released, with its check.** 1.0.0 released only the episodes that passed the
  robot-side check. 1.1.0 releases every human episode that passes the human quality check and
  labels each one with the result of the robot-side check (`check_passed`, `check_failed`):

  | dataset | 1.0.0 | 1.1.0 released | 1.1.0 passing |
  |---|---|---|---|
  | ARCADE-Checkout-FFW-SH5 | 94 episodes | 111 episodes, 27,024 steps | 83 episodes, 18,954 steps |
  | ARCADE-Checkout-UR10e | 45 episodes | 110 episodes, 96,040 steps | 67 episodes, 54,678 steps |
  | ARCADE-Checkout-G1 | 80 episodes | 111 episodes, 14,104 steps | 98 episodes, 12,665 steps |

  49 episodes pass the check on all three robots. One human episode (`J06112_left`) has no UR10e
  trajectory: for one of its holds the grasp planner found no grasp that either arm can reach.
* **UR10e: an arm against itself.** The retargeting keeps the wrist and gripper clear of the same
  arm's forearm and upper arm where another arm configuration reaches the grasp, and the robot-side
  check has a rule for it (`arm_self_contact`: 18 of the 110 episodes).
* **UR10e: joint ranges and smooth arm separation.** Every joint stays inside its position range in
  the URDF (new check rule `joint_limit`), and the pass that keeps the two arms apart keeps each step
  close to the previous one within the joint velocity limits, so it adds no jitter.
* **`left_holding` / `right_holding`.** The last two values of `observation.environment_state` are
  renamed from `left_carrying` / `right_carrying` and have one meaning on every robot: 1 while that
  robot hand, arm or gripper holds the product, both 1 during a hand-over. In 1.0.0 the FFW-SH5
  flags marked the one hand the product was attached to. `meta/modality.json`: the state key is
  `holding` (was `carrying`).
* **Episode metadata and splits.** `meta/episodes.jsonl` (v2.1) and the episodes table (v3.0) gain
  `check_passed` and `check_failed`. The passing episodes come first (in time order), then the
  rejected ones. `meta/info.json -> splits` has `train`, `val` and `test` over the passing episodes
  (the time blocks of the human data, boundary episodes in none of them) and `rejected`;
  `meta/splits.json` lists them, with `boundary` and `rejected`.
* **Raw outputs.**
  * `PREFIX_obj.npz` has `obj_holding` `(n, 2)` for every robot.
  * `PREFIX_obj.json`, per episode: `holding` (the runs in which a hand or arm holds the product)
    and `check {passed, failed}`. FFW-SH5 also has `carrying` (the runs of the hand the product is
    attached to), next to `obj_carrier` in the npz.
  * `PREFIX_ik.json`: `release`, `counter`, `args` reduced to `fps` (UR10e: also the joint velocity
    and acceleration limits), and `episodes` as a list of ids. The `barriers` entry and the list of
    run settings are gone.
  * Run logs are no longer shipped.
* **Counter.** One footprint for the human data and every robot: `x ∈ [-0.551, 0.057]`,
  `y ∈ [-0.840, 0.541]` (m, counter frame), in `PREFIX_ik.json -> counter` and
  `meta/arcade.json -> counter`.
* **FFW-SH5.** During a hold the fingers are solved onto the product surface (thumb opposite the
  fingers), starting from the human finger pose, instead of only following the human fingertips.
  While the product is carried the hand keeps that grasp, so the product does not move inside the
  robot hand. At a release the fingers peel off and the hand lifts away before retreating. The
  timeline is slowed where the arm cannot follow. New check rule `grasp_contact`: no grasp was found in which thumb and fingers
  reach the product surface without going into it.
* **Unitree G1.** The robot stands on a 0.35 m step in front of the counter (`PREFIX_ik.json ->
  stand`, `meta/arcade.json -> stand`). The G1 is about 1.3 m tall: without the step the counter top
  is at its chest and it works with raised arms. Robot world: floor `z = 0`, step top `z = 0.35`,
  counter top `z = 0.80`. During a hand-over the holds of the two hands overlap.
* **Two UR10e.** The data covers all the episodes, not only those in which the shopper uses both
  hands: in 65 of the 110 episodes both arms handle the product and in 45 one arm does everything.
  The motion is re-timed toward joint velocity limits (120 / 120 / 180 / 180 / 180 / 180 deg/s) and
  joint acceleration limits (150 / 150 / 250 / 300 / 300 / 300 deg/s²), recorded in
  `PREFIX_ik.json -> args`; the acceleration values are exceeded at 2.5 % of the steps.
* **2F-140 opening.** A released `finger_joint` value belongs to the 2F-140 model the retargeting used,
  not to the URDF built by `fetch_robot.sh`: at the same value that URDF's pads are 12 to 16 mm closer.
  `arcade_retarget.ur10e_2f140.urdf_finger_joint` converts through the opening, the config gains the URDF's
  own table (`urdf_finger_joint`, `urdf_pad_gap_m`), and the preview renderer draws the gripper at the
  opening the data means (the UR10e clips are re-rendered). The unused config entries `rest_q` and
  `pad_centre_along_m` are removed.
* **No physics replay results.** The `physics_all_held` flag that the G1 data had in 1.0.0 is
  removed: physics replay results will be published for all three robots together in a later
  release.
* **Products de-identified.** Public product ids (`bottle_a`, `bottle_b`, `bottle_c`, `box_flat`,
  `box_long`) and de-identified mesh textures, as in ARCADE-Checkout-Human 1.1.0.
* **Samples.** `samples/` has the same three episodes for every robot (`J00601_right`,
  `J02562_right`, `J03826_left`), including episodes that fail the robot-side check.
* **The solver is not part of this repository.** The FFW-SH5 retargeting solver and its input
  adapter, part of the package in 1.0.0, are removed: for all three robots the repository reads,
  checks, exports and renders the released data. How the data was produced and checked is described
  in `docs/RETARGETING_FFW_SH5.md` (renamed from `docs/RETARGETING.md`),
  `docs/RETARGETING_UR10E.md` and `docs/RETARGETING_G1.md`. The `solver` package extra is removed:
  the tests recompute the released poses from the released joints with the forward kinematics in
  `arcade_retarget.urdf_fk`, which needs numpy only.

## 1.0.0

First public release of the robot datasets: the checkout episodes of the recording session on three robots.

* **ARCADE-Checkout-FFW-SH5:** 94 episodes on the ROBOTIS AI Worker FFW-SH5 (18,119 steps,
  11 tasks).
* **ARCADE-Checkout-UR10e:** 45 episodes on two UR10e arms with Robotiq 2F-140 grippers
  (42,087 steps, 10 tasks).
* **ARCADE-Checkout-G1:** 80 episodes on the Unitree G1 humanoid with Dex3-1 hands (10,505 steps,
  12 tasks), each with `physics_all_held` from a MuJoCo replay of its grasps.
* LeRobot codebase v3.0 and v2.1, state only, plus the raw retargeting outputs.
* Package `arcade-retarget`: LeRobot exporter, renderer, robot models and checks.
  `retarget/*/fetch_robot.sh` fetches each robot description from its maker's repository at a
  fixed commit.
