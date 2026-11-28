# Datasheets

The datasets are on Hugging Face with **gated access** (request access on the dataset page):
[ARCADE-Checkout-Human](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-Human) · [ARCADE-Checkout-FFW-SH5](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-FFW-SH5) · [ARCADE-Checkout-UR10e](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-UR10e) · [ARCADE-Checkout-G1](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-G1). They are updated to 1.1.0 as part of this release. The repository also ships a
small sample of each dataset in the exact release format: 4 human episodes and the same 3 episodes for every robot
([`human/samples`](../human/samples), [`robots/samples`](../robots/samples)). The datasets and the samples are
licensed under [CC BY-NC 4.0](../LICENSE) (non-commercial use with attribution). The product textures are
de-identified: brand names, logos, codes and readable text are replaced by colour fields and unreadable glyphs.

All four datasets are built from one human reconstruction, the ARCADE-Checkout-Human 1.1.0 release: the same
episodes, the same hand and product poses, the same holding labels and the same counter. Every episode is released
and labelled by an automatic check (`check_passed`, `check_failed`): the **quality check** for the human data, a
**robot-side check** for each robot. Training splits use only the passing episodes; the others are listed as
`rejected`. 49 episodes pass the check on all three robots.

## ARCADE-Checkout-Human: human demonstrations

| | |
|---|---|
| Description | A shopper picking up, inspecting, passing between hands and putting down retail products at a self-checkout counter, as metric 3-D data |
| Owner | SpaceVision AI |
| Version | 1.1.0, processed 2026-11-25 |
| Intended use | Learning manipulation from human demonstrations: grasp and hand-over timing, bimanual coordination, product pose. Retargeting to robots. Hand-object interaction research |
| Collection | 4 synchronised cameras (top, left, right, front), ChArUco-calibrated, 19.94 fps. One session (`capture_20260818_01`), one shopper, one counter, 5 products |
| Annotation | Automatic. 3-D body (fixed bone lengths) and hands (hand rig) fitted to multi-view keypoints; product 6-DoF per episode: resting on a stable face, or tied to the carrying hand with the multi-view masks as evidence; grasp/release events from hand-object interaction; the hand carrying the product. Measured-vs-fitted flags for body joints (`body/filled`) and hands (`gap_filled`); per-frame agreement of the product pose with the masks (`object/mask_iou`). How the poses are corrected: [human/docs/METHOD.md](../human/docs/METHOD.md#corrections) |
| Selection | Every segmented episode of the session is released. An automatic quality check of physical plausibility and agreement with the camera masks labels each episode (`check_passed`, `check_failed` = the rules it fails): 111 of 114 pass ([rules](../human/docs/METHOD.md#quality-check)). `time_split` uses the passing episodes and lists the others as `rejected` |
| Content | 114 episodes, 17,188 episode frames from 8,969 unique session frames (7.5 min; episodes overlap). Of the 111 passing episodes: 55 hand-to-hand passes, 12 both-hands holds, 43 one-hand, 1 picked up twice. 23 body joints, 21 landmarks per hand, wrist SE(3), product 6-DoF, 424 grasp/release events, per-hand holding and carrying intervals, segmentation masks (3 views), 5 product meshes (`bottle_a`, `bottle_b`, `bottle_c`, `box_flat`, `box_long`) with de-identified textures |
| Format | HDF5 + JSON + OBJ/MTL/PNG + PNG masks (one zip per episode). Reader, validator, quality summary and renderer: [`human/`](../human) |
| Size | core 41 MB without the masks. Masks for every episode are in the Hugging Face release; the repository ships masks only for the sample episodes |
| RGB video | RGB video is not part of the release. For recordings whose participants consented to sharing, it can be provided on request, after consultation and de-identification |
| Camera calibration | Camera intrinsics and extrinsics are not released |
| Product mass and friction | Not measured |
| Limitations | One shopper, one session, 5 products. No scan events. No motion-capture reference exists: the mask IoU measures agreement with the masks the pose was fitted to, which is self-consistency, not accuracy against an independent ground truth. The carried product pose is constrained by the hand, so in-hand rotation of the product is under-represented |

## ARCADE-Checkout-FFW-SH5: FFW-SH5 robot data

| | |
|---|---|
| Description | ARCADE-Checkout-Human episodes retargeted to the ROBOTIS AI Worker FFW-SH5, as a state-only LeRobot dataset |
| Source | ARCADE-Checkout-Human 1.1.0 (recorded in the raw outputs, `PREFIX_ik.json -> release`) |
| Selection | Every human episode that passes the quality check is released: 111. An automatic robot-side check of the robot motion (finger self-collision and speed, touching the product before the grasp or after the release, the counter, hand overlap, the idle hand, arm-branch flips, the product in the hand and on its path, grasp contact) labels each episode (`check_passed`, `check_failed`): 83 pass. The `train`, `val` and `test` splits use the passing episodes; the 28 others are in the `rejected` split. Rules failed (an episode can fail several): `product_path` 16, `arm_branch` 7, `hand_overlap` 7, `idle_hand` 3, `touch_after_release` 2, `grasp_contact` 1 ([rules](../robots/docs/RETARGETING_FFW_SH5.md#robot-side-check)) |
| Owner | SpaceVision AI |
| Version | 1.1.0, processed 2026-11-25 |
| Intended use | Training and evaluating state-based manipulation policies for a mobile bimanual humanoid with dexterous hands; retargeting research |
| Out of scope | Running policies on hardware without physical validation |
| Generation | Kinematic retargeting. The robot hands follow the human hand pose and finger shape frame by frame, and inverse kinematics solves the arms and the mobile base on the ROBOTIS URDF (lift fixed). During a hold the fingers are solved onto the product surface, thumb opposite the fingers, starting from the human finger pose; while the product is carried the hand keeps that grasp and the product is attached to the robot hand; at a release the fingers peel off and the hand lifts away before retreating. No teleoperation, no learned model; not executed on a robot |
| Content | 111 episodes, 27,024 steps at 20 fps; the 83 passing episodes have 18,954 steps. 151 / 230 / 432 steps per episode (min / median / max). 60-D joint state and action, 9-D product state (pose, `left_holding`, `right_holding`), 12 language tasks (11 among the passing episodes). Time splits: train 61 / val 10 / test 9 (+3 boundary) / rejected 28 |
| Format | LeRobot codebase v3.0 and v2.1 (parquet), plus the raw retargeting outputs (npz). Code: [`robots/`](../robots) |
| Size | LeRobot 14 MB (v3.0) / 18 MB (v2.1); raw outputs 12 MB |
| Not included | Contact forces. The solver is not part of this repository. The trajectories are kinematic: no physics validation is part of this release, and they were not executed on a robot. Whether a five-finger grasp holds depends on finger compliance, friction and millimetre-level finger placement, which a kinematic retargeting does not determine ([Hands and grippers](../robots/README.md#hands-and-grippers)) |

## ARCADE-Checkout-UR10e: UR10e + Robotiq 2F-140 robot data

| | |
|---|---|
| Description | ARCADE-Checkout-Human episodes retargeted to two Universal Robots UR10e arms, left and right of the shopper's position, with Robotiq 2F-140 grippers on fixed bases, as a state-only LeRobot dataset |
| Source | ARCADE-Checkout-Human 1.1.0 (recorded in the raw outputs, `PREFIX_ik.json -> release`) |
| Selection | Every human episode that passes the quality check and has a UR10e trajectory is released: 110 (one, `J06112_left`, has none: for one of its holds the grasp planner found no grasp that either arm can reach). An automatic robot-side check of the robot motion (a grasp for every hold, the product moving or hovering unheld, the product shifted more than 50 mm, the counter, contact between the arms, between the grippers and of an arm with itself, the gripper inside the product, joint speed and joint range) labels each episode (`check_passed`, `check_failed`): 67 pass. The `train`, `val` and `test` splits use the passing episodes; the 43 others are in the `rejected` split. Rules failed (an episode can fail several): `arm_self_contact` 18, `product_shift` 15, `gripper_contact` 12, `counter` 8, `no_grasp` 7, `gripper_in_product` 3, `gripper_in_product_after_release` 2, `gripper_in_product_before_grasp` 2, `product_hovers` 2 ([rules](../robots/docs/RETARGETING_UR10E.md#robot-side-check)) |
| Owner | SpaceVision AI |
| Version | 1.1.0, processed 2026-11-25 |
| Intended use | Training and evaluating state-based manipulation policies for two industrial arms with parallel grippers, including hand-overs; retargeting research |
| Out of scope | Running policies on hardware without physical validation |
| Generation | Kinematic, grasp-first. Nothing follows the shopper frame by frame: a parallel-jaw grasp is planned per hold on the product's box or cylinder, and the arm tracks the product. The product moves only while a gripper holds it and may shift up to 50 mm from the human path. The motion is re-timed toward joint velocity limits of 120 / 120 / 180 / 180 / 180 / 180 deg/s and joint acceleration limits of 150 / 150 / 250 / 300 / 300 / 300 deg/s² (recorded in `PREFIX_ik.json -> args`); velocities stay within the limits at all but 1 of 97,035 steps, accelerations exceed the acceleration values at 2.9 % of the steps. Robot descriptions from Universal Robots and ROS-Industrial. No teleoperation, no learned model; not executed on a robot |
| Content | 110 episodes, 96,040 steps at 20 fps; the 67 passing episodes have 54,678 steps. The data is made with two arms: in 65 of the 110 episodes both arms handle the product (a hand-over or a both-arm hold) and in 45 one arm does everything; among the 67 passing, 32 with both arms and 35 with one. 478 / 828 / 1625 steps per episode (min / median / max). 14-D joint state and action (2 × 6 arm joints, 2 gripper joints), 9-D product state (pose, `left_holding`, `right_holding`), 11 language tasks (9 among the passing episodes). Time splits: train 51 / val 6 / test 7 (+2 boundary) / rejected 44 |
| Format | LeRobot codebase v3.0 and v2.1 (parquet), plus the raw outputs (npz). Code: [`robots/`](../robots) |
| Size | LeRobot 13 MB (v3.0) / 16 MB (v2.1); raw outputs 13 MB |
| Not included | Contact forces. The solver is not part of this repository. The trajectories are kinematic: no physics validation is part of this release, and they were not executed on a robot |

## ARCADE-Checkout-G1: Unitree G1 + Dex3-1 robot data

| | |
|---|---|
| Description | ARCADE-Checkout-Human episodes retargeted to a Unitree G1 humanoid (29 body joints, free-floating pelvis) with Dex3-1 three-finger hands, standing on a 0.35 m step in front of the counter, as a state-only LeRobot dataset |
| Source | ARCADE-Checkout-Human 1.1.0 (recorded in the raw outputs, `PREFIX_ik.json -> release`) |
| Selection | Every human episode that passes the quality check is released: 111. An automatic robot-side check of the robot motion (the robot hand gripping and touching the product, the hand inside the product, the counter, hand–hand and arm–body contact, joint speed, balance, and the feet staying within 10 mm of their place) labels each episode (`check_passed`, `check_failed`): 98 pass. The `train`, `val` and `test` splits use the passing episodes; the 13 others are in the `rejected` split. Rules failed (an episode can fail several): `hand_in_product` 5, `not_gripping` 5, `hand_contact` 3, `no_contact` 2, `hand_in_product_before_grasp` 2, `arm_body_contact` 1 ([rules](../robots/docs/RETARGETING_G1.md#robot-side-check)) |
| Owner | SpaceVision AI |
| Version | 1.1.0, processed 2026-11-25 |
| Intended use | Training and evaluating state-based whole-body manipulation policies for a humanoid with three-finger hands, including hand-overs; retargeting research |
| Out of scope | Running policies on hardware without physical validation; walking (the feet stay in place) |
| Stand | The robot stands on a 0.35 m step in front of the counter (`PREFIX_ik.json -> stand`, `meta/arcade.json -> stand`). The G1 is about 1.3 m tall: without the step the counter top is at its chest and it works with raised arms (upper arm 80° from hanging in the median, against the shopper's 24°); on the step the median is 39°. The step height was chosen once for the whole dataset. Robot world: floor `z = 0`, step top `z = 0.35`, counter top `z = 0.80` |
| Generation | Kinematic, whole-body: legs, waist, arms and hands on the Unitree URDF, with the feet fixed on the step. The approach follows the human fingertips, and a three-finger grasp is planned per hold near the human grasp; candidate grasps are ranked with a short simulated carry during planning. The product keeps the human path, lightly smoothed while held. The timing is the human timing, slowed around hand-over grabs. Robot description from Unitree. No teleoperation, no learned model; not executed on a robot |
| Content | 111 episodes, 14,104 steps at 20 fps; the 98 passing episodes have 12,665 steps. By the robot's own holds: 54 passes, 14 both-hands holds, 43 one-hand (passing: 49 / 12 / 37). 60 / 124 / 234 steps per episode (min / median / max). 50-D state and action (43 joints and the pelvis pose), 9-D product state (pose, `left_holding`, `right_holding`), 12 language tasks. Time splits: train 73 / val 10 / test 12 (+3 boundary) / rejected 13 |
| Format | LeRobot codebase v3.0 and v2.1 (parquet), plus the raw outputs (npz). Code: [`robots/`](../robots) |
| Size | LeRobot 8 MB (v3.0) / 10 MB (v2.1); raw outputs 5 MB |
| Not included | Contact forces. The solver is not part of this repository. The trajectories are kinematic: no physics validation is part of this release, and they were not executed on a robot |
