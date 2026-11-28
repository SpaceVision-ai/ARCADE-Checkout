# Glossary

| term | meaning |
|---|---|
| **ARCADE-Checkout-Human** | the human dataset, in `human/` (package `arcade-human`) |
| **ARCADE-Checkout-FFW-SH5**, **ARCADE-Checkout-UR10e**, **ARCADE-Checkout-G1** | the robot datasets (LeRobot), in `robots/` (package `arcade-retarget`). All three are built from the same ARCADE-Checkout-Human release, recorded in their raw outputs (`PREFIX_ik.json -> release`) |
| **session** | one continuous recording at the counter. The current release has one, `capture_20260818_01` |
| **episode** | one product handled by the shopper: lead-in while it rests, grasp(s), handling, release(s), tail. Every segmented episode is released, with the result of its check |
| **`episode_id`** | a stable, opaque key such as `J03826_left`, shared by the human and robot datasets. Use `core_window`, `first_grasp_hand` and `hands` for timing and hands |
| **product** | one of 5 retail products with de-identified public ids: the bottles `bottle_a`, `bottle_b`, `bottle_c` and the boxes `box_flat`, `box_long`. The meshes have measured dimensions and approximate shapes; their textures are de-identified (brand names, logos, codes and readable text replaced by colour fields and unreadable glyphs) |
| **phase** | per hand: 0 before the grasp, 1 just before it (the last 6 frames), 2 hold (its holding interval; both hands during a hand-over), 3 after. The same in the human data and, through `left_holding` / `right_holding`, in the robot data. See the [README](../README.md#what-happens-in-an-episode) |
| **core window** | the segmented action of an episode, without the lead-in and tail context |
| **`task_kind`** | what the hands do in the core window: `pass` (the product ends in the other hand), `both_hands` (both hands hold it, the first hand puts it down), `one_hand`, or `repeated` (put down and picked up again). The UR10e data uses `pass`, `both_arms` and `one_arm`, from the robot's own grasps; the G1 data uses the human names, from the robot's own holds |
| **holding** (human data) | `interaction/<hand>/holding`: the frames in which a given hand holds the product, from its grasp to its release. Both hands hold during a hand-over. It agrees with the events within one frame (410 of 412 events in the passing episodes) |
| **carrying** (human data) | `interaction/<hand>/carrying`: the frames in which the product moves with a given hand. One hand carries at a time, also while both hands hold the product |
| **`left_holding` / `right_holding`** (robot data) | the last two values of `observation.environment_state`: 1 while that robot hand, arm or gripper holds the product, both 1 during a hand-over. The meaning is the same on all three robots. In `meta/modality.json` the state key is `holding`; in the raw outputs, `obj_holding` and `PREFIX_obj.json -> holding`. The FFW-SH5 raw outputs also keep the hand the product is attached to (`carrying`, `obj_carrier`) |
| **HOI label** | the 2-D hand-object-interaction signal: a hand holds an object in at least 2 of 3 camera views |
| **grasp / release event** | the frame a hand starts / stops holding the product |
| **counter frame** | the common 3-D frame: `x` forward across the counter, `y` the shopper's left, `z` up, counter top at `z = 0`, metres |
| **counter footprint** | the extent of the counter top in the counter frame: `x ∈ [-0.551, 0.057]`, `y ∈ [-0.840, 0.541]` (m), a box around every resting product position of the session. Recorded in the human `meta/info.json -> counter` and in every robot's `PREFIX_ik.json -> counter` and `meta/arcade.json -> counter` |
| **product frame** | the frame of a product mesh: bounding-box centre, cylinder axis or box `h` edge along `z` |
| **6-DoF** | position and orientation of the product per frame |
| **measured / filled** | whether a joint was observed in that frame or taken from the fitted skeleton (`body/filled`, `gap_filled`) |
| **mask IoU** | per-frame agreement of the posed product with its camera masks (`object/mask_iou`). The pose was fitted to these masks, so it measures self-consistency, not accuracy against an independent reference |
| **quality check** | the automatic check of the human data: physical plausibility and agreement of the posed product with the camera masks. It labels every episode and removes none ([rules](../human/docs/METHOD.md#quality-check)) |
| **robot-side check** | the automatic check of a robot's retargeted motion, one set of rules per robot. It labels every episode of the robot dataset and removes none (rules: [FFW-SH5](../robots/docs/RETARGETING_FFW_SH5.md#robot-side-check), [UR10e](../robots/docs/RETARGETING_UR10E.md#robot-side-check), [G1](../robots/docs/RETARGETING_G1.md#robot-side-check)) |
| **`check_passed` / `check_failed`** | per episode, in the episode metadata of all four datasets: whether the episode passes its check (the quality check in the human data, the robot-side check in a robot dataset), and the ids of the rules it fails (empty when it passes) |
| **`rejected` split** | the episodes that fail their check. They are released, but belong to none of `train`, `val` and `test`: `time_split` returns them as `rejected` (human data), and the robot datasets list them in `meta/info.json -> splits` and `meta/splits.json`, after the passing episodes |
| **retargeting** | mapping the human motion and the product interaction onto the robot's joints |
| **FFW-SH5** | ROBOTIS AI Worker with a swerve base, lift, two 7-DoF arms, a 2-DoF head and two HX5-D20 hands (`robot_type` `ffw_sh5_rev1`) |
| **UR10e + 2F-140** | two Universal Robots UR10e arms (6 joints each) with Robotiq 2F-140 parallel grippers on fixed bases (`robot_type` `ur10e_2f140_dual`) |
| **G1 + Dex3-1** | a Unitree G1 humanoid (29 body joints, free-floating pelvis) with two Dex3-1 three-finger hands, 7 joints each (`robot_type` `unitree_g1_dex3`) |
| **stand** (G1) | the 0.35 m step in front of the counter that the G1 stands on (`PREFIX_ik.json -> stand`, `meta/arcade.json -> stand`). The G1 is about 1.3 m tall; without the step the counter top is at its chest. Robot world: floor `z = 0`, step top `z = 0.35`, counter top `z = 0.80` |
| **`finger_joint`** | the one actuated joint of a 2F-140 gripper, rad: 0 open, larger closes. `arcade_retarget.ur10e_2f140.gripper_gap` converts it to the opening in metres, which is what a released value means; `urdf_finger_joint` gives the value with that opening on the fetched URDF |
| **`source_frame` / `tmap`** | for each robot step, the (fractional) source frame it shows. Steps are slower than the human where the robot cannot keep up |
| **`counter_h`** | the height of the counter top above the robot's floor (0.80 m, assumed) |
| **LeRobot v3.0 / v2.1** | the dataset layouts read by `lerobot` ≥ 0.4 and by `lerobot` 0.3.x; both are provided |
