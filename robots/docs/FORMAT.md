# Output formats

The raw retargeting outputs are NumPy archives with JSON sidecars per robot (`PREFIX_*`): three
for FFW-SH5 (`_ik`, `_hand`, `_obj`), two for the other robots (`_ik`, `_obj`).
`python -m arcade_retarget.export_lerobot` turns them into a LeRobot dataset.

Three robots share these conventions. The sections below describe the **FFW-SH5** files. The
**two UR10e + Robotiq 2F-140** and **Unitree G1 + Dex3-1** files differ where noted in their own
sections ([UR10e](#two-ur10e--robotiq-2f-140), [G1](#unitree-g1--dex3-1)).

Every released episode is in the files, whether or not it passes the robot-side check. The check
result travels with each episode: `PREFIX_obj.json -> episodes[<episode_id>] -> check` in the raw
outputs, `check_passed` and `check_failed` in the LeRobot episodes metadata, and the `rejected`
split.

## Frames and time

* **Counter frame.** All ARCADE-Checkout-Human data and the retargeting's Cartesian outputs use the
  counter frame: `x` forward across the counter, `y` the shopper's left, `z` up, and the
  counter top at `z = 0` (see [human/docs/COORDINATES.md](../../human/docs/COORDINATES.md)).
* **Robot world.** The robot stands on a floor `counter_h` below the counter top (0.80 m,
  assumed), so `robot_world = counter_frame + [0, 0, counter_h]`. The swerve base's planar
  joint `(x, y, yaw)` lives in this frame. The G1 does not stand on the floor but on a 0.35 m
  step ([G1](#unitree-g1--dex3-1)): floor `z = 0`, top of the step `z = 0.35`, counter top `z = 0.80`.
* **Output steps.** The retargeting may slow parts of an episode down when the robot cannot
  follow the human's speed. Each output step therefore maps to a fractional source frame
  (`tmap`). Steps follow the capture clock, 19.94 fps; the LeRobot export stamps them at a
  nominal 20 fps because LeRobot needs an integer rate.

## `PREFIX_ik.npz` (+ `.json`)

Keys are `"<episode_id>|<field>"`. `n` is the number of output steps of the episode.

| field | shape | meaning |
|---|---|---|
| `frames` | `(n,) int` | nearest source (session) frame of each step |
| `tmap` | `(n,) float` | fractional source frame of each step (never decreasing) |
| `q` | `(n, 14) float32` | arm joint positions, rad, in `joint_names` order (`arm_l_joint1..7`, `arm_r_joint1..7`) |
| `joint_names` | `(14,) str` | |
| `base_traj` | `(n, 4) float32` | swerve base `[x, y, yaw, lift]` in the robot world (m, m, rad, m; yaw unwrapped). The lift stays at 0 |
| `base` | `(6,)` | reference base placement of the episode, `[x, y, -counter_h, yaw, 0, dx]`, where `dx` is a back-off from the counter. The exporter and the renderer read `base_traj`, not this |
| `head` | `(n, 2) float32` | `head_joint1`, `head_joint2` (rad). The camera looks at the active hand |
| `w` | `(n,) float32` | the larger of the two hands' `<hand>__w` |
| `grasp_ok` | `(k,) str` | one entry per carrying interval, `"<episode>\|<hand>\|<frame>\|G"` (source frame of its start) |
| `<hand>__w` | `(n,) float32` | 1 while the hand follows the shopper (inside the window), 0 at home, in between during the home transitions |
| `<hand>__win` | `(4,) int` | steps where the transition from home starts, the window starts, the window ends and the transition home ends (-1: none) |
| `<hand>__hand_T` | `(n, 4, 4) float32` | reached robot hand frame (MCP centre), counter frame |
| `<hand>__target_T` | `(n, 4, 4) float32` | planned hand target, counter frame. Outside the window: the reached hand frame |
| `<hand>__err` | `(n, 3) float32` | tracking error inside the window: position (mm), rotation (deg), elbow direction (mm). 0 outside |
| `<hand>__avoid` | `(n, 3) float32` | offset applied to the human wrist path so the hand clears the product and the counter before the first grasp and retreats after the last release (m) |
| `<hand>__yield` | `(n,) float32` | blend of an idle hand toward the rest pose beside the body (0: follows the shopper's hand) |

`<hand>` is `left` or `right`. The steps outside `<hand>__win[0] .. <hand>__win[3]` of a hand are
at its home pose. Idle steps before the robot leaves home and after it is back are trimmed, so
most episodes start and end in a home transition.

`PREFIX_ik.json`:

* `kind`, `robot`, `urdf`: what the file is and which robot description it was made with;
* `release`: the human data it was made from, `{name, version, session}` (ARCADE-Checkout-Human
  1.1.0, session `capture_20260818_01`). Every robot's file records the same release;
* `counter`: the counter footprint `x0, x1, y0, y1` (m), `yaw` and `top_z`, counter frame:
  `x ∈ [-0.551, 0.057]`, `y ∈ [-0.840, 0.541]`, a box around every resting product position of the
  session. The human data records the same footprint (`meta/info.json -> counter`,
  [human/docs/COORDINATES.md](../../human/docs/COORDINATES.md));
* `counter_h`: floor to counter top, 0.80 m (assumed);
* `args`: `fps`, the capture rate the exporter and the renderer read;
* `mobile_base`;
* `episodes`: the list of episode ids in the archive;
* `provenance`: processing date.

## `PREFIX_hand.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `<hand>__fingers` | `(n, 20) float32` | HX5-D20 finger joints `finger_{l,r}_joint1..20` (rad), on output steps. At home every joint is 0 (clipped to its limits) |
| `finger_joint_names` | `(20,) str` | joint names for the left hand. The right hand uses the same indices with `finger_r_` |

`PREFIX_hand.json` names the `_ik` archive it belongs to and the number of episodes.

## `PREFIX_obj.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `obj_T` | `(n, 4, 4) float32` | product pose on output steps, counter frame. While carried it is attached to the robot hand; after a release it settles onto a stable face |
| `obj_ok` | `(n,) bool` | the human product pose existed at the step before gap filling |
| `obj_T_s1` | `(n, 4, 4) float32` | the product pose of the human data at the step's source frame |
| `obj_holding` | `(n, 2) bool` | the left / right robot hand holds the product; both are true during a hand-over. Every robot's `_obj` archive has this field |
| `obj_carrier` | `(n,) int8` | the robot hand the product is attached to: -1 none, 0 left, 1 right (FFW-SH5 only) |
| `obj_dev` | `(n,) float32` | distance between `obj_T` and `obj_T_s1` while carried (m); NaN otherwise |

`PREFIX_obj.json` holds `kind`, `ik` (the archive it belongs to), `release` and `episodes`.
`episodes[<episode_id>]` contains:

* `dims`: product shape and size (`box`: `l`, `w`, `h`; `cylinder`: `r`, `h`; metres);
* `product`: the public product id (`bottle_a`, `bottle_b`, `bottle_c`, `box_flat`, `box_long`);
* `mesh`: path inside the ARCADE-Checkout-Human release, and `mesh_perm`, the axis permutation it was baked with;
* `holding`: the intervals in which a robot hand holds the product, `[{hand, start, end}]` in
  output steps. The two hands' intervals overlap during a hand-over;
* `carrying`: the intervals of the hand the product is attached to, `[{hand, start, end}]` in
  output steps; one hand at a time (FFW-SH5 only);
* `counter`: `{center, size, yaw}`;
* `track`: how far the carried product is from the human product path, in mm (`hold_dev_p50_mm`,
  `hold_dev_p90_mm`, `hold_dev_max_mm`, `hold_rot_max_deg`) and where it was put down (`place_dev_mm`);
* `check`: the robot-side check, `{passed, failed}`. `failed` lists the ids of the rules the
  episode fails (empty when it passes); the rules are in
  [RETARGETING_FFW_SH5.md](RETARGETING_FFW_SH5.md#robot-side-check).

## LeRobot dataset (codebase v3.0 and v2.1)

`python -m arcade_retarget.export_lerobot --retarget PREFIX --release ARCADE_HUMAN --out DIR`
writes a LeRobot **v2.1** dataset. `ARCADE_HUMAN` is the ARCADE-Checkout-Human release the retargeting came
from; it supplies the time splits and the task sentences (see [Splits](#splits)). Without it
every episode goes to the `train` split and the exporter warns. Current `lerobot` (0.4 and later) reads **v3.0**; convert
with lerobot's own converter:

```bash
python -m lerobot.scripts.convert_dataset_v21_to_v30 --repo-id=local/arcade_ffw_sh5 --root=DIR --push-to-hub=false
```

Both layouts hold the same rows. The samples ship both: `samples/lerobot_ffw_sh5_v3.0` and
`samples/lerobot_ffw_sh5_v2.1`.

```
v2.1  DIR/meta/info.json, tasks.jsonl, episodes.jsonl, episodes_stats.jsonl, stats.json,
               modality.json (slice map), arcade.json (provenance), splits.json (with --release)
      DIR/data/chunk-000/episode_000000.parquet ...
v3.0  DIR/meta/info.json, tasks.parquet, stats.json, episodes/chunk-000/file-000.parquet,
               arcade.json, splits.json
      DIR/data/chunk-000/file-000.parquet
```

`robot_type` is `ffw_sh5_rev1`, the ROBOTIS name of the robot (URDF `ffw_sh5_rev1_follower`).
`fps` is 20.

| feature | dtype, shape | content |
|---|---|---|
| `observation.state` | float32[60] | joint positions, layout below |
| `action` | float32[60] | the next step's `observation.state` (position targets). The last step holds its position |
| `observation.environment_state` | float32[9] | `product_x`, `product_y`, `product_z`, `product_qx`, `product_qy`, `product_qz`, `product_qw`: the product pose in the robot world; then `left_holding`, `right_holding` (0/1): 1 while that robot hand, arm or gripper holds the product (`obj_holding`). Both are 1 during a hand-over. Same meaning on all three robots |
| `source_frame` | float32[1] | the ARCADE-Checkout-Human session frame the step shows (fractional where the robot was slowed down). Not an observation: it links each step to the human data |
| `timestamp`, `frame_index`, `episode_index`, `index`, `task_index`, `next.done` | | standard LeRobot columns |

### State and action layout (60-D)

| index | names | unit | URDF limits |
|---|---|---|---|
| 0–6 | `arm_l_joint1` … `arm_l_joint7` | rad | j1 ±3.14, j2 [0, 3.14], j3 ±3.14, j4 [−2.94, 1.08], j5 ±3.14, j6 ±1.57, j7 [−1.58, 1.82] |
| 7–13 | `arm_r_joint1` … `arm_r_joint7` | rad | as the left arm, mirrored: j2 [−3.14, 0], j7 [−1.82, 1.58] |
| 14–33 | `finger_l_joint1` … `finger_l_joint20` | rad | HX5-D20, 4 joints per finger: thumb 1–4, index 5–8, middle 9–12, ring 13–16, little 17–20 |
| 34–53 | `finger_r_joint1` … `finger_r_joint20` | rad | same order as the left hand |
| 54–55 | `head_joint1`, `head_joint2` | rad | [−0.23, 0.70], [−0.35, 0.35] |
| 56 | `lift_joint` | m | [−0.5, 0] |
| 57–59 | `base_x`, `base_y`, `base_yaw` | m, m, rad | swerve base pose in the robot world |

The names are also in `meta/info.json -> features -> observation.state -> names`, and
`meta/modality.json` (v2.1 layout) groups the same slices (`left_arm`, `right_arm`, `left_hand`,
`right_hand`, `head`, `lift`, `base`; `product_pose` and `holding` point into
`observation.environment_state`). For the physical meaning of each joint see the ROBOTIS
AI Worker and HX5-D20 documentation.

### Episodes

Episode order: the episodes that pass the robot-side check come first, in time order, then the
rejected ones. The sample therefore holds `J02562_right`, `J03826_left`, `J00601_right` as episodes
0, 1, 2 (UR10e: `J02562_right`, `J00601_right`, `J03826_left`).

`meta/episodes.jsonl` (v2.1) and the episodes table `meta/episodes/chunk-000/file-000.parquet`
(v3.0) hold, per episode:

| field | content |
|---|---|
| `episode_index`, `tasks`, `length` | standard LeRobot fields |
| `source_episode_id` | the ARCADE-Checkout-Human episode id |
| `product` | the public product id |
| `source_frames` | first and last session frame of the episode |
| `check_passed` | the episode passes the robot-side check (bool) |
| `check_failed` | ids of the rules it fails (empty list when it passes) |

### Tasks

Each episode has one language task, built from which hand picks the product up, whether both
hands hold it, and which hand puts it down. The full dataset has 12 distinct tasks (11 among the
passing episodes), for example:

* *"Pick up the bottle from the checkout counter with the right hand and put it down."*
* *"Pick up the box from the checkout counter with the left hand, pass it to the right hand, and put it down."*
* *"Pick up the bottle from the checkout counter with the right hand, hold it with both hands, and put it down with the right hand."*

With `--release` the FFW-SH5 task is the one of the ARCADE-Checkout-Human episode; without it, the
task is built from the `holding` intervals of `PREFIX_obj.json`.

### Splits

The episodes overlap in time (they come from one continuous recording), so random splits
leak. With `--release`:

* `meta/info.json -> splits` holds episode ranges: `train`, `val` and `test` are the time blocks of
  `arcade_human.splits.time_split`, restricted to the episodes that pass the robot-side check, and
  `rejected` is the range of the episodes that fail it. In the sample:
  `{"train": "0:2", "rejected": "2:3"}`.
* `meta/splits.json` lists the episode indices of `train`, `val`, `test`, `boundary` and
  `rejected`. Boundary episodes pass the check but straddle two time blocks, so they belong to
  none of `train`, `val` and `test`.

Full FFW-SH5 dataset: train 61, val 10, test 9, boundary 3 and rejected 28 episodes (`rejected` is
`83:111`). To train on passing episodes only, select the `train` range, or filter the episodes
metadata on `check_passed`.

Without `--release` there is no time split: `splits` is `{"train": "0:N"}` over every episode,
rejected ones included, and `meta/splits.json` is not written.

### `meta/arcade.json`

Provenance of the export, for every robot:

* `source`, `version` (the exporter's), `counter_h`, `frame` (robot world), `capture_fps`, `fps`
  and `timing`;
* `retarget`: the human release the retargeting came from, `{name, version, session}` (copied
  from `PREFIX_ik.json -> release`);
* `counter`: the counter footprint, as in `PREFIX_ik.json`;
* UR10e: `bases` and `mount`; G1: `pelvis` (where the pelvis pose is in the state) and `stand`
  (the step the robot stands on).

## Two UR10e + Robotiq 2F-140

Files `ur10e_2f140_ik.npz` / `.json` and `ur10e_2f140_obj.npz` / `.json` (no hand file: the
grippers have one joint each). Frames and time are as above: Cartesian values in the counter frame,
one output step per 1/19.94 s, `tmap` the fractional session frame of each step. The robot is
re-timed to joint velocity and acceleration limits and moves slower than the shopper, so several
steps can show the same session frame. Approach steps planned before the session start stay at
frame 0.

### `ur10e_2f140_ik.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `frames` | `(n,) int` | nearest session frame of each step |
| `tmap` | `(n,) float32` | fractional session frame of each step (never decreasing) |
| `q` | `(n, 12) float32` | arm joint positions, rad, in `joint_names` order: `left_shoulder_pan_joint` … `left_wrist_3_joint`, then the right arm |
| `joint_names` | `(12,) str` | |
| `gripper` | `(n, 2) float32` | `finger_joint` of the left and right 2F-140, rad: 0 open. The values belong to the 2F-140 model the retargeting used; what they mean is the opening in metres, `arcade_retarget.ur10e_2f140.gripper_gap`. On the URDF built by `fetch_robot.sh` the same value closes 12 to 16 mm further: convert with `urdf_finger_joint` ([gripper](../retarget/universal_robots_ur10e_robotiq_2f140/README.md#gripper)) |
| `gripper_names` | `(2,) str` | `left_finger_joint`, `right_finger_joint` |
| `phase` | `(n, 2) int8` | per arm: -1 at rest, 0 approach, 1 gripper closed on the product, 2 retreat |
| `<arm>__gripper_T` | `(n, 4, 4) float32` | pose of the gripper base (`robotiq_arg2f_base_link`), counter frame. Forward kinematics of `q` on the fetched URDF reproduces it |

`ur10e_2f140_ik.json` holds:

* `kind`, `robot` (`ur10e_2f140`), `robot_type` and `urdf`;
* `release`, `counter`, `counter_h`, `episodes` and `provenance`, as for FFW-SH5;
* `bases` and `mount`: the two base poses and the gripper mount, robot world, as in
  [`configs/ur10e_2f140.json`](../arcade_retarget/configs/ur10e_2f140.json);
* `args`: `fps`, and the joint limits of the re-timing, `joint_velocity_limit_deg_s`
  (120, 120, 180, 180, 180, 180) and `joint_acceleration_limit_deg_s2`
  (150, 150, 250, 300, 300, 300), in arm joint order.

### `ur10e_2f140_obj.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `obj_T` | `(n, 4, 4) float32` | product pose on output steps, counter frame. The product moves only while a gripper holds it; between grasps it rests on the counter. Steps before the first and after the last known pose repeat the nearest one |
| `obj_ok` | `(n,) bool` | the product pose is known at this step (not repeated) |
| `obj_holding` | `(n, 2) bool` | the left / right gripper is closed on the product (`phase == 1`); both during a hand-over |

`ur10e_2f140_obj.json -> episodes[<episode_id>]` holds:

* `dims`, `product`, and `mesh` (the path inside the ARCADE-Checkout-Human release) with `mesh_perm`;
* `holding`: `[{arm, start, end}]` in output steps;
* `task_kind`: `one_arm`, `pass` or `both_arms`, from the robot's own grasps;
* `counter`;
* `track`: how far the retargeting moved the product from the human product path so that a
  gripper always holds it while it moves (`product_shift_max_mm`,
  `product_shift_frames_over_20mm`). More than 50 mm fails the rule `product_shift`;
* `check`: `{passed, failed}`, with the rule ids of
  [RETARGETING_UR10E.md](RETARGETING_UR10E.md#robot-side-check).

### LeRobot dataset

Same layout, columns, episode order and splits as the FFW-SH5 dataset above, with:

* `robot_type` `ur10e_2f140_dual`;
* `observation.state` / `action`: **14-D**;
* `observation.environment_state`: product pose, then `left_holding`, `right_holding` = the
  gripper is closed on the product. Both are 1 during a hand-over;
* tasks from the robot's own grasps (which arm picks up, whether both hold, which arm puts down),
  with "arm" in place of "hand": 11 distinct tasks in the full dataset (9 among the passing
  episodes);
* `meta/arcade.json` adds `bases` and `mount`.

| index | names | unit | URDF limits |
|---|---|---|---|
| 0–5 | `left_shoulder_pan_joint`, `left_shoulder_lift_joint`, `left_elbow_joint`, `left_wrist_1_joint`, `left_wrist_2_joint`, `left_wrist_3_joint` | rad | ±2π, elbow ±π |
| 6–11 | `right_…` | rad | as the left arm |
| 12–13 | `left_finger_joint`, `right_finger_joint` | rad | [0, 0.7] |

`meta/modality.json` groups `left_arm`, `right_arm`, `left_gripper`, `right_gripper`. Full
dataset: 110 episodes; train 52, val 6, test 7, boundary 2 and rejected 43 (`rejected` is
`67:110`).

## Unitree G1 + Dex3-1

Files `g1_dex3_ik.npz` / `.json` and `g1_dex3_obj.npz` / `.json`. There is no hand file: the Dex3-1
finger joints are part of `q`. Frames and time follow the conventions above:

* Cartesian values are in the counter frame.
* Each output step is 1/19.94 s, and `tmap` is the fractional session frame of each step.
* The robot follows the shopper's clock, except around hand-over grabs, where the timeline is
  slowed. Several steps can then show the same session frame.

**The robot stands on a step.** The G1 is about 1.3 m tall and the counter top is 0.80 m above the
floor, so the data puts the robot on a 0.35 m step in front of the counter. The step is recorded
as `stand` in `g1_dex3_ik.json` and in `meta/arcade.json`: its `height` and its footprint
`x0, x1, y0, y1` in the counter frame. In the robot world the floor is `z = 0`, the top of the
step `z = 0.35` and the counter top `z = 0.80`; the feet are on the step. A simulation of the data
needs the step as well as the counter ([why](RETARGETING_G1.md#the-step)).

### `g1_dex3_ik.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `frames` | `(n,) int` | nearest session frame of each step |
| `tmap` | `(n,) float32` | fractional session frame of each step (never decreasing) |
| `q` | `(n, 43) float32` | joint positions, rad, in `joint_names` order (URDF order: left leg, right leg, waist, left arm, left hand, right arm, right hand) |
| `joint_names` | `(43,) str` | |
| `pelvis` | `(n, 7) float32` | pelvis pose `[x, y, z, qx, qy, qz, qw]`, counter frame; the quaternion is scalar-last |
| `phase` | `(n, 2) int8` | per hand: 0 free, 1 approach, 2 holding the product, 3 retreat. This is the robot's own plan, not the episode phases of the [README](../../README.md#what-happens-in-an-episode) |
| `com` | `(n, 3) float32` | centre of mass, counter frame |
| `<hand>__tips` | `(n, 3, 3) float32` | thumb, index and middle fingertip points, counter frame. Forward kinematics of `pelvis` + `q` on the fetched URDF reproduces them (`arcade_retarget.g1_dex3.fingertips`) |

`g1_dex3_ik.json` holds:

* `kind`, `robot` (`g1_dex3`), `robot_type` and `urdf`;
* `release`, `counter`, `counter_h`, `episodes` and `provenance`, as for FFW-SH5;
* `stand`, the step the robot stands on: `height` (0.35 m) and its footprint `x0, x1, y0, y1`,
  counter frame;
* `counter_edge`, the near edge `x(y)` of the counter that the legs, pelvis and torso stay behind;
* `tip_offset_m`, the offset of the fingertip points along the last finger links;
* `args`: `fps` and the `stance` (both feet stay where they start).

### `g1_dex3_obj.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `obj_T` | `(n, 4, 4) float32` | product pose on output steps, counter frame. This is the human product path, lightly smoothed while a hand holds it. Steps before the first and after the last known pose repeat the nearest one |
| `obj_ok` | `(n,) bool` | the product pose is known at this step (not repeated) |
| `obj_holding` | `(n, 2) bool` | the left / right hand holds the product (`phase == 2`); both are true during a hand-over |

`g1_dex3_obj.json -> episodes[<episode_id>]` holds:

* `dims`, `product`, and `mesh` (the path inside the ARCADE-Checkout-Human release) with `mesh_perm`;
* `holding`: `[{hand, start, end}]` in output steps. The two hands' intervals overlap during a
  hand-over;
* `task_kind`: `one_hand`, `pass` or `both_hands`, from the robot's own holds;
* `counter`;
* `check`: `passed` and `failed` (the rule ids of
  [RETARGETING_G1.md](RETARGETING_G1.md#robot-side-check)), plus per-episode extremes of the
  robot-side measurements: `hand_in_product_max_mm`, `hands_min_distance_mm`,
  `arm_body_min_distance_mm`, `counter_max_mm`, `com_margin_min_mm` and `foot_move_max_mm`.

### LeRobot dataset

Same layout, columns, episode order and splits as the FFW-SH5 dataset above, with these
differences:

* `robot_type` is `unitree_g1_dex3`.
* `observation.state` and `action` are **50-D**: the 43 joints, then the pelvis pose in the robot
  world (floor `z = 0`; the robot stands on the step, whose top is `z = 0.35`).
* In `observation.environment_state`, the product pose is followed by `left_holding` and
  `right_holding`: the hand holds the product. Both are 1 during a hand-over.
* Tasks come from the robot's own holds, with the same sentences as the human data: 12 distinct
  tasks in the full dataset.
* `meta/arcade.json` adds `pelvis` and `stand`.

| index | names | unit | URDF limits |
|---|---|---|---|
| 0–5 | `left_hip_pitch_joint`, `left_hip_roll_joint`, `left_hip_yaw_joint`, `left_knee_joint`, `left_ankle_pitch_joint`, `left_ankle_roll_joint` | rad | hip pitch [−2.53, 2.88], roll [−0.52, 2.97], yaw ±2.76, knee [−0.09, 2.88], ankle pitch [−0.87, 0.52], roll ±0.26 |
| 6–11 | `right_…` | rad | as the left leg, mirrored (hip roll [−2.97, 0.52]) |
| 12–14 | `waist_yaw_joint`, `waist_roll_joint`, `waist_pitch_joint` | rad | yaw ±2.62, roll ±0.52, pitch ±0.52 |
| 15–21 | `left_shoulder_pitch_joint`, `left_shoulder_roll_joint`, `left_shoulder_yaw_joint`, `left_elbow_joint`, `left_wrist_roll_joint`, `left_wrist_pitch_joint`, `left_wrist_yaw_joint` | rad | shoulder pitch [−3.09, 2.67], roll [−1.59, 2.25], yaw ±2.62, elbow [−1.05, 2.09], wrist roll ±1.97, pitch ±1.61, yaw ±1.61 |
| 22–28 | `left_hand_index_0_joint`, `left_hand_index_1_joint`, `left_hand_middle_0_joint`, `left_hand_middle_1_joint`, `left_hand_thumb_0_joint`, `left_hand_thumb_1_joint`, `left_hand_thumb_2_joint` | rad | index and middle [−1.57, 0] / [−1.75, 0], thumb ±1.05, [−0.61, 1.05], [0, 1.75] |
| 29–35 | `right_shoulder_pitch_joint` … `right_wrist_yaw_joint` | rad | as the left arm, mirrored |
| 36–42 | `right_hand_index_0_joint` … `right_hand_thumb_2_joint` | rad | the left hand's limits mirrored |
| 43–49 | `pelvis_x`, `pelvis_y`, `pelvis_z`, `pelvis_qx`, `pelvis_qy`, `pelvis_qz`, `pelvis_qw` | m, unit quaternion | robot world |

`meta/modality.json` groups these slices as `left_leg`, `right_leg`, `waist`, `left_arm`,
`left_hand`, `right_arm`, `right_hand` and `pelvis`. Full dataset: 111 episodes; train 73, val 10,
test 12, boundary 3 and rejected 13 (`rejected` is `98:111`).
