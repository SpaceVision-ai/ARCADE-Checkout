# Glossary

| term | meaning |
|---|---|
| **ARCADE-Checkout-Human** | the human dataset, in `human/` (package `arcade-human`) |
| **ARCADE-Checkout-FFW-SH5**, **ARCADE-Checkout-UR10e**, **ARCADE-Checkout-G1** | the robot datasets (LeRobot), in `robots/` (package `arcade-retarget`) |
| **session** | one continuous recording at the counter. The current release has one, `capture_20260818_01` |
| **episode** | one product handled by the shopper: lead-in while it rests, grasp(s), handling, release(s), tail |
| **`episode_id`** | a stable, opaque key such as `J03826_left`, shared by the human and robot datasets. Use `core_window`, `first_grasp_hand` and `hands` for timing and hands |
| **phase** | per hand: 0 before the grasp, 1 just before it (the last 6 frames), 2 hold (its carrying interval), 3 after. See the [README](../README.md#what-happens-in-an-episode) |
| **core window** | the segmented action of an episode, without the lead-in and tail context |
| **`task_kind`** | what the hands do in the core window: `pass` (the product ends in the other hand), `both_hands` (both hands hold it, the first hand puts it down), `one_hand`, or `repeated` (put down and picked up again). The UR10e data uses `pass`, `both_arms` and `one_arm`, from the robot's own grasps; the G1 data uses the human names, from the robot's own holds |
| **holding interval** | frames in which a given hand holds the product, from its grasp to its release. It agrees with the events within one frame (358 of 360 events) |
| **carrying interval** | frames in which the product moves with a given hand (one hand at a time, also while both hands hold it). The FFW-SH5 data attaches the product to this hand (`obj_carrier`, `left_carrying` / `right_carrying`); in the UR10e and G1 data `left_carrying` / `right_carrying` mark a gripper or hand that holds the product, both during a hand-over |
| **HOI label** | the 2-D hand-object-interaction signal: a hand holds an object in at least 2 of 3 camera views |
| **grasp / release event** | the frame a hand starts / stops holding the product |
| **counter frame** | the common 3-D frame: `x` forward across the counter, `y` the shopper's left, `z` up, counter top at `z = 0`, metres |
| **product frame** | the frame of a product mesh: bounding-box centre, cylinder axis or box `h` edge along `z` |
| **6-DoF** | position and orientation of the product per frame |
| **measured / filled** | whether a joint was observed in that frame or taken from the fitted skeleton (`body/filled`, `gap_filled`) |
| **mask IoU** | per-frame agreement of the posed product with its camera masks (`object/mask_iou`) |
| **quality check** | the automatic test of physical plausibility and agreement with the masks; only passing episodes are released |
| **retargeting** | mapping the human motion and the product interaction onto the robot's joints |
| **FFW-SH5** | ROBOTIS AI Worker with a swerve base, lift, two 7-DoF arms, a 2-DoF head and two HX5-D20 hands (`robot_type` `ffw_sh5_rev1`) |
| **UR10e + 2F-140** | two Universal Robots UR10e arms (6 joints each) with Robotiq 2F-140 parallel grippers on fixed bases (`robot_type` `ur10e_2f140_dual`) |
| **G1 + Dex3-1** | a Unitree G1 humanoid (29 body joints, free-floating pelvis) with two Dex3-1 three-finger hands, 7 joints each (`robot_type` `unitree_g1_dex3`) |
| **`physics_all_held`** | G1 only: the episode's grasps kept the product in every hold in a MuJoCo replay (0.3 kg product, assumed) |
| **`finger_joint`** | the one actuated joint of a 2F-140 gripper, rad: 0 open, larger closes. `arcade_retarget.ur10e_2f140.gripper_gap` converts it to the opening in metres |
| **`source_frame` / `tmap`** | for each robot step, the (fractional) source frame it shows. Steps are slower than the human where the robot cannot keep up |
| **`counter_h`** | the height of the counter top above the robot's floor (0.80 m) |
| **LeRobot v3.0 / v2.1** | the dataset layouts read by `lerobot` ≥ 0.4 and by `lerobot` 0.3.x; both are provided |
