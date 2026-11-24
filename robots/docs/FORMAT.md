# Output formats

`python -m arcade_retarget.ffw_sh5 --out PREFIX` writes three NumPy archives with JSON
sidecars. `python -m arcade_retarget.export_lerobot` turns them into a LeRobot dataset.

Three robots share these conventions. The sections below describe the **FFW-SH5** files. The
**two UR10e + Robotiq 2F-140** and **Unitree G1 + Dex3-1** files differ where noted in their own
sections ([UR10e](#two-ur10e--robotiq-2f-140), [G1](#unitree-g1--dex3-1)).

## Frames and time

* **Counter frame.** All ARCADE-Checkout-Human data and the retargeting's Cartesian outputs use the
  counter frame: `x` forward across the counter, `y` the shopper's left, `z` up, and the
  counter top at `z = 0` (see [human/docs/COORDINATES.md](../../human/docs/COORDINATES.md)).
* **Robot world.** The robot stands on a floor `counter_h` below the counter top (0.80 m by
  default), so `robot_world = counter_frame + [0, 0, counter_h]`. The swerve base's planar
  joint `(x, y, yaw)` lives in this frame.
* **Output steps.** The retargeting may slow parts of an episode down when the robot cannot
  follow the human's speed. Each output step therefore maps to a fractional source frame
  (`tmap`). Steps follow the capture clock, 19.94 fps; the LeRobot export stamps them at a
  nominal 20 fps because LeRobot needs an integer rate.

## `PREFIX_ik.npz` (+ `.json`)

Keys are `"<episode_id>|<field>"`. `n` is the number of output steps of the episode.

| field | shape | meaning |
|---|---|---|
| `frames` | `(n,) int` | nearest source (session) frame of each step |
| `tmap` | `(n,) float32` | fractional source frame of each step |
| `q` | `(n, 14) float32` | arm joint positions, rad, in `joint_names` order (`arm_l_joint1..7`, `arm_r_joint1..7`) |
| `joint_names` | `(14,) str` | |
| `base_traj` | `(n, 4) float32` | swerve base `[x, y, yaw, lift]` in the robot world (m, m, rad, m; yaw unwrapped) |
| `base` | `(6,)` | initial base placement `[x, y, -counter_h, yaw, 0, dx]`, where `dx` is the chosen back-off |
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

The steps outside `<hand>__win[0] .. <hand>__win[3]` of a hand are at its home pose. Idle
steps before the robot leaves home and after it is back are trimmed, so most episodes start and
end in a home transition.

`PREFIX_ik.json`:

* `kind`, `urdf`: what produced the file;
* `counter`: the counter extent used, `x0, x1, y0, y1`, counter frame (inferred from resting
  products, see [human/docs/COORDINATES.md](../../human/docs/COORDINATES.md));
* `counter_h`;
* `release`: the ARCADE-Checkout-Human name, version and session;
* `args`: every solver parameter;
* `mobile_base`, `barriers`, `episodes`, `minutes` (wall time of the run);
* `provenance`: processing date (released files) or `workers` (local runs).

`PREFIX_ik.log`: lines that start with `<episode_id> n` are per-episode summaries (output
steps, tracking error percentiles, joint-limit use, base motion, fingertip errors, finger
self-penetration, clearance shifts, home transitions). Lines with `retime round` log the
re-timing rounds.

## `PREFIX_hand.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `<hand>__fingers` | `(n, 20) float32` | HX5-D20 finger joints `finger_{l,r}_joint1..20` (rad), on output steps. At home every joint is 0 (clipped to its limits) |
| `finger_joint_names` | `(20,) str` | joint names for the left hand. The right hand uses the same indices with `finger_r_` |

## `PREFIX_obj.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `obj_T` | `(n, 4, 4) float32` | product pose on output steps, counter frame. While carried it rides with the robot hand; after a release it settles onto a stable face |
| `obj_ok` | `(n,) bool` | the human product pose existed at the step before gap filling |
| `obj_T_s1` | `(n, 4, 4) float32` | the human product path on output steps (interpolated at `tmap`: position linearly, rotation geodesically) |
| `obj_carrier` | `(n,) int8` | the robot hand the product rides with: -1 none, 0 left, 1 right |
| `obj_dev` | `(n,) float32` | distance between `obj_T` and `obj_T_s1` while carried (m); NaN otherwise |

`PREFIX_obj.json -> episodes[<episode_id>]` contains:

* `dims`: product shape and size;
* `product`;
* `mesh`: path inside the ARCADE-Checkout-Human release, and `mesh_perm`, the axis permutation it was baked with;
* `holding`: the carrying intervals, `[{hand, start, end}]` in output steps;
* `counter`: `{center, size, yaw}`;
* `track`: how far the carried product is from the human product path, in mm (`hold_dev_p50_mm`,
  `hold_dev_p90_mm`, `hold_dev_max_mm`, `hold_rot_max_deg`) and where it was put down (`place_dev_mm`).

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
| `observation.environment_state` | float32[9] | product pose `[x, y, z, qx, qy, qz, qw]` in the robot world, then `left_carrying`, `right_carrying` (0/1): the hand the product rides with (`obj_carrier`); at most one is 1 |
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
`meta/modality.json` groups the same slices (`left_arm`, `right_arm`, `left_hand`,
`right_hand`, `head`, `lift`, `base`; `product_pose` and `carrying` point into
`observation.environment_state`). For the physical meaning of each joint see the ROBOTIS
AI Worker and HX5-D20 documentation.

### Tasks

Each episode has one language task, built from which hand picks the product up, whether both
hands hold it, and which hand puts it down. The full dataset has 11 distinct tasks, of these
three forms:

* *"Pick up the bottle from the checkout counter with the right hand and put it down."*
* *"Pick up the box from the checkout counter with the left hand, pass it to the right hand, and put it down."*
* *"Pick up the bottle from the checkout counter with the right hand, hold it with both hands, and put it down with the right hand."*

`episodes.jsonl` (v2.1) also records the ARCADE-Checkout-Human `source_episode_id`, the `product` and
the `source_frames`.

### Splits

The episodes overlap in time (they come from one continuous recording), so random splits
leak. With `--release`, `meta/info.json -> splits` holds the time blocks of
`arcade_human.splits.time_split` as episode ranges (full dataset: train `0:71`, val `72:80`,
test `81:94`), and `meta/splits.json` lists them, plus the 2 boundary episodes (71, 80) that
belong to none. With `--release` the task also comes from the ARCADE-Checkout-Human episode. Without
`--release` there is no time split: `splits` is `{"train": "0:N"}` and `meta/splits.json` is not
written.

## Two UR10e + Robotiq 2F-140

Files `ur10e_2f140_ik.npz` / `.json` and `ur10e_2f140_obj.npz` / `.json` (no hand file: the
grippers have one joint each). Frames and time are as above: Cartesian values in the counter frame,
one output step per 1/19.94 s, `tmap` the fractional session frame of each step. The robot is
re-timed to the UR10e joint speed limits and moves slower than the shopper, so several steps can
show the same session frame. Approach steps planned before the session start stay at frame 0.

### `ur10e_2f140_ik.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `frames` | `(n,) int` | nearest session frame of each step |
| `tmap` | `(n,) float32` | fractional session frame of each step (never decreasing) |
| `q` | `(n, 12) float32` | arm joint positions, rad, in `joint_names` order: `left_shoulder_pan_joint` … `left_wrist_3_joint`, then the right arm |
| `joint_names` | `(12,) str` | |
| `gripper` | `(n, 2) float32` | `finger_joint` of the left and right 2F-140, rad: 0 open, up to 0.648 in the data (URDF limit 0.7). Opening in metres: `arcade_retarget.ur10e_2f140.gripper_gap` |
| `gripper_names` | `(2,) str` | `left_finger_joint`, `right_finger_joint` |
| `phase` | `(n, 2) int8` | per arm: -1 at rest, 0 approach, 1 gripper closed on the product, 2 retreat |
| `<arm>__gripper_T` | `(n, 4, 4) float32` | pose of the gripper base (`robotiq_arg2f_base_link`), counter frame. Forward kinematics of `q` on the fetched URDF reproduces it |

`ur10e_2f140_ik.json`: `kind`, `robot` (`ur10e_2f140`), `robot_type`, `urdf`, `counter`,
`counter_h`, `bases` and `mount` (robot world, as in
[`configs/ur10e_2f140.json`](../arcade_retarget/configs/ur10e_2f140.json)), `rest_q`, `source`
(the session), `args` (`fps` and the joint speed and acceleration limits of the re-timing),
`episodes`, `provenance` (processing date). `ur10e_2f140_ik.log` has one summary line per episode.

### `ur10e_2f140_obj.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `obj_T` | `(n, 4, 4) float32` | product pose on output steps, counter frame. The product moves only while a gripper holds it; between grasps it rests on the counter. Steps before the first and after the last known pose repeat the nearest one |
| `obj_ok` | `(n,) bool` | the product pose is known at this step (not repeated) |
| `obj_holding` | `(n, 2) bool` | the left / right gripper is closed on the product (`phase == 1`); both during a hand-over |

`ur10e_2f140_obj.json -> episodes[<episode_id>]`: `dims`, `product`, `mesh` (path inside the
ARCADE-Checkout-Human release) and `mesh_perm`, `holding` (`[{arm, start, end}]`, output steps),
`task_kind` (`one_arm`, `pass`, `both_arms`), `counter`, and `track`: how far the retargeting
moved the product from the path its grasps were planned on, so that a gripper always holds it
while it moves (`product_shift_max_mm`, `product_shift_frames_over_20mm`; at most 1 mm in the
released episodes).

### LeRobot dataset

Same layout, columns and splits as the FFW-SH5 dataset above, with:

* `robot_type` `ur10e_2f140_dual`;
* `observation.state` / `action`: **14-D**;
* `observation.environment_state`: product pose, then `left_carrying`, `right_carrying` = the
  gripper is closed on the product. Unlike FFW-SH5, both are 1 during a hand-over;
* tasks from the robot's own grasps (which arm picks up, whether both hold, which arm puts down),
  with "arm" in place of "hand": 10 distinct tasks in the full dataset;
* `meta/arcade.json` adds `bases` and `mount`.

| index | names | unit | URDF limits |
|---|---|---|---|
| 0–5 | `left_shoulder_pan_joint`, `left_shoulder_lift_joint`, `left_elbow_joint`, `left_wrist_1_joint`, `left_wrist_2_joint`, `left_wrist_3_joint` | rad | ±2π, elbow ±π |
| 6–11 | `right_…` | rad | as the left arm |
| 12–13 | `left_finger_joint`, `right_finger_joint` | rad | [0, 0.7] |

`meta/modality.json` groups `left_arm`, `right_arm`, `left_gripper`, `right_gripper`. With the
full ARCADE-Checkout-Human release as `--release`, the time splits are train `0:35`, val `35:36`, test
`37:45` (1 boundary episode).

## Unitree G1 + Dex3-1

Files `g1_dex3_ik.npz` / `.json` and `g1_dex3_obj.npz` / `.json`. There is no hand file: the Dex3-1
finger joints are part of `q`. Frames and time follow the conventions above:

* Cartesian values are in the counter frame.
* Each output step is 1/19.94 s, and `tmap` is the fractional session frame of each step.
* The robot follows the shopper's clock, except around hand-over grabs, where the timeline is
  slowed. Several steps can then show the same session frame.

### `g1_dex3_ik.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `frames` | `(n,) int` | nearest session frame of each step |
| `tmap` | `(n,) float32` | fractional session frame of each step (never decreasing) |
| `q` | `(n, 43) float32` | joint positions, rad, in `joint_names` order (URDF order: left leg, right leg, waist, left arm, left hand, right arm, right hand) |
| `joint_names` | `(43,) str` | |
| `pelvis` | `(n, 7) float32` | pelvis pose `[x, y, z, qx, qy, qz, qw]`, counter frame. Pinocchio's free-flyer configuration is `pelvis` followed by `q` (`arcade_retarget.g1_dex3.pin_configuration`) |
| `phase` | `(n, 2) int8` | per hand: 0 free, 1 approach, 2 holding the product, 3 retreat. This is the robot's own plan, not the episode phases of the [README](../../README.md#what-happens-in-an-episode) |
| `com` | `(n, 3) float32` | centre of mass, counter frame |
| `<hand>__tips` | `(n, 3, 3) float32` | thumb, index and middle fingertip points, counter frame. Forward kinematics of `pelvis` + `q` on the fetched URDF reproduces them (`arcade_retarget.g1_dex3.pin_model`) |

`g1_dex3_ik.json` holds:

* `kind`, `robot` (`g1_dex3`), `robot_type` and `urdf`;
* `counter`, the counter extent;
* `counter_edge`, the near edge `x(y)` that the legs, pelvis and torso stay behind;
* `counter_h` and `tip_offset_m`;
* `source`, the session;
* `args`: `fps`, the stance, the joint speed caps, the product path smoothing and the hand-over
  re-timing;
* `physics`, the replay settings: product mass and friction, and what each verdict means;
* `episodes` and `provenance` (processing date).

`g1_dex3_ik.log` has one summary line per episode.

### `g1_dex3_obj.npz` (+ `.json`)

| field | shape | meaning |
|---|---|---|
| `obj_T` | `(n, 4, 4) float32` | product pose on output steps, counter frame. This is the recorded path, smoothed while a hand holds it. Steps before the first and after the last known pose repeat the nearest one |
| `obj_ok` | `(n,) bool` | the product pose is known at this step (not repeated) |
| `obj_holding` | `(n, 2) bool` | the left / right hand holds the product (`phase == 2`); both are true during a hand-over |

`g1_dex3_obj.json -> episodes[<episode_id>]` holds:

* `dims`, `product`, and `mesh` (the path inside the ARCADE-Checkout-Human release) with `mesh_perm`;
* `holding`: `[{hand, start, end}]` in output steps;
* `task_kind`: `one_hand`, `pass` or `both_hands`;
* `counter`;
* `check`: per-episode extremes of the robot-side measurements. These are
  `hand_in_product_max_mm`, `hands_min_distance_mm`, `arm_body_min_distance_mm`, `counter_max_mm`,
  `com_margin_min_mm`, `foot_slide_max_mm` and `steps_taken`;
* `physics`: `all_held`, plus `holds`, a list of `{hand, start, end, verdict}`. `verdict` is
  `held`, `slipped`, `lost` or `no_carry`. Method:
  [RETARGETING_G1.md](RETARGETING_G1.md#physics-replay).

### LeRobot dataset

Same layout, columns and splits as the FFW-SH5 dataset above, with these differences:

* `robot_type` is `unitree_g1_dex3`.
* `observation.state` and `action` are **50-D**: the 43 joints, then the pelvis pose in the robot
  world (floor `z = 0`).
* In `observation.environment_state`, the product pose is followed by `left_carrying` and
  `right_carrying`: the hand holds the product. Both are 1 during a hand-over.
* Tasks come from the robot's own holds, with the same sentences as the human data: 12 distinct
  tasks in the full dataset.
* `meta/episodes.jsonl` (v2.1) and the episodes table (v3.0) add `physics_all_held`.
* `meta/arcade.json` adds `pelvis` and `physics`.

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
`left_hand`, `right_arm`, `right_hand` and `pelvis`. With the full ARCADE-Checkout-Human release as
`--release`, the time splits are train `0:63`, val `64:70` and test `71:80` (2 boundary episodes).
