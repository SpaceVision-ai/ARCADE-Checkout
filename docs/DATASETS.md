# Datasheets

The datasets are on Hugging Face with **gated access** (request access on the dataset page):
[ARCADE-Checkout-Human](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-Human) · [ARCADE-Checkout-FFW-SH5](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-FFW-SH5) · [ARCADE-Checkout-UR10e](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-UR10e) · [ARCADE-Checkout-G1](https://huggingface.co/datasets/SpaceVision-AI/ARCADE-Checkout-G1). The repository also ships a
2-episode sample of each dataset in the exact release format
([`human/samples`](../human/samples), [`robots/samples`](../robots/samples)). The datasets and the samples are
licensed under [CC BY-NC 4.0](../LICENSE) (non-commercial use with attribution). The packaging artwork in the
product textures belongs to the product makers.

## ARCADE-Checkout-Human: human demonstrations

| | |
|---|---|
| Description | A shopper picking up, inspecting, passing between hands and putting down retail products at a self-checkout counter, as metric 3-D data |
| Owner | SpaceVision AI |
| Version | 1.0.0, processed 2026-11-10 |
| Intended use | Learning manipulation from human demonstrations: grasp and hand-over timing, bimanual coordination, product pose. Retargeting to robots. Hand-object interaction research |
| Collection | 4 synchronised cameras (top, left, right, front), ChArUco-calibrated, 19.94 fps |
| Annotation | Automatic. 3-D body (fixed bone lengths) and hands (hand rig) fitted to multi-view keypoints; product 6-DoF fitted per episode to multi-view masks; grasp/release events from hand-object interaction; the hand carrying the product. Measured-vs-fitted flags for body joints (`body/filled`) and hands (`gap_filled`); per-frame agreement of the product pose with the masks (`object/mask_iou`) |
| Selection | Episodes that pass an automatic check of physical plausibility and agreement with the camera masks |
| Content | 97 episodes (49 hand-to-hand passes, 10 both-hands holds, 37 one-hand, 1 picked up twice), 23 body joints, 21 landmarks per hand, wrist SE(3), product 6-DoF, 360 grasp/release events, 263,441 segmentation masks (3 views), textured product meshes |
| Format | HDF5 + JSON + OBJ/MTL/PNG + PNG masks (one zip per episode). Reader, validator, quality summary and renderer: [`human/`](../human) |
| Size | core 49 MB, masks 2.7 GB, total 2.7 GB |
| RGB video | Will be released after de-identification |
| Product mass and friction | Not measured |

## ARCADE-Checkout-FFW-SH5: FFW-SH5 robot data

| | |
|---|---|
| Description | ARCADE-Checkout-Human episodes retargeted to the ROBOTIS AI Worker FFW-SH5, as a state-only LeRobot dataset |
| Selection | Human episodes whose robot motion also passes an automatic check of collisions, arm-branch flips and the product staying in the hand |
| Owner | SpaceVision AI |
| Version | 1.0.0, processed 2026-11-10 |
| Intended use | Training and evaluating state-based manipulation policies for a mobile bimanual humanoid with dexterous hands; retargeting research |
| Out of scope | Running policies on hardware without physical validation |
| Generation | Kinematic retargeting: the robot hand pose and finger joints fitted to the human hand, then Pink IK for arms and base on the ROBOTIS URDF; the carried product is attached to the robot hand. No teleoperation, no learned model, no physics simulation; not executed on a robot |
| Content | 94 episodes, 18,119 steps at 20 fps. 60-D joint state and action, 9-D product state (pose and carrying hand), 11 language tasks, time splits |
| Format | LeRobot codebase v3.0 and v2.1 (parquet), plus the raw retargeting outputs (npz). Code: [`robots/`](../robots) |
| Size | LeRobot 11 MB (v3.0) / 14 MB (v2.1); raw outputs 9 MB |
| Not included | Contact forces, physics validation. Hand-product contact is not modelled: the fingers may penetrate the product mesh |

## ARCADE-Checkout-UR10e: UR10e + Robotiq 2F-140 robot data

| | |
|---|---|
| Description | The two-handed checkout episodes of the recording session retargeted to two Universal Robots UR10e arms with Robotiq 2F-140 grippers on fixed bases, as a state-only LeRobot dataset |
| Selection | Two-handed episodes whose robot motion passes an automatic check of arm and gripper contact, the robot below the counter top, the gripper inside the product, joint speed, and the product moving only while a gripper holds it; listed in ARCADE-Checkout-Human |
| Owner | SpaceVision AI |
| Version | 1.0.0, processed 2026-11-16 |
| Intended use | Training and evaluating state-based manipulation policies for two industrial arms with parallel grippers, including hand-overs; retargeting research |
| Out of scope | Running policies on hardware without physical validation |
| Generation | Kinematic, grasp-first: a parallel-jaw grasp planned per holding interval on the product's box or cylinder, exact and damped least-squares IK for the UR10e, a barrier QP between the arms and above the counter, and re-timing to the UR10e joint speed limits. Robot descriptions from Universal Robots and ROS-Industrial. No teleoperation, no learned model, no physics simulation; not executed on a robot |
| Content | 45 episodes, 42,087 steps at 20 fps. 14-D joint state and action (2 × 6 arm joints, 2 gripper joints), 9-D product state (pose and the grippers closed on it), 10 language tasks, time splits |
| Format | LeRobot codebase v3.0 and v2.1 (parquet), plus the raw outputs (npz). Code: [`robots/`](../robots) |
| Size | LeRobot 6 MB (v3.0) / 7 MB (v2.1); raw outputs 5 MB |
| Not included | Contact forces, physics validation. Joint accelerations are not limited |

## ARCADE-Checkout-G1: Unitree G1 + Dex3-1 robot data

| | |
|---|---|
| Description | The checkout episodes of the recording session retargeted to a Unitree G1 humanoid (29 body joints, free-floating pelvis) with Dex3-1 three-finger hands, standing where the shopper stood, as a state-only LeRobot dataset |
| Selection | Episodes whose robot motion passes an automatic check of the robot hand gripping while the shopper holds, hand and counter penetration, hand–hand and arm–body contact, joint speed, balance (centre of mass over the feet) and the feet staying in place; listed in ARCADE-Checkout-Human |
| Owner | SpaceVision AI |
| Version | 1.0.0, processed 2026-11-21 |
| Intended use | Training and evaluating state-based whole-body manipulation policies for a humanoid with three-finger hands, including hand-overs; retargeting research |
| Out of scope | Running policies on hardware without physical validation; walking (the robot never steps) |
| Generation | Grasp-first, whole-body: a three-finger grasp planned per holding interval on the product's box or cylinder and ranked in a physics test, then Pink IK for legs, waist, arms and hands on the Unitree URDF with the feet fixed, the centre of mass over the feet, and collision barriers. The product keeps its recorded path, smoothed while held; the timeline is slowed around hand-over grabs. Robot description from Unitree. No teleoperation, no learned model; not executed on a robot |
| Physics | Each hold is replayed in MuJoCo with the product as a free 0.3 kg box or cylinder (friction 1; assumed, not measured): 45 of 80 episodes keep the product in every hold (`physics_all_held`) |
| Content | 80 episodes, 10,505 steps at 20 fps. 50-D state and action (43 joints and the pelvis pose), 9-D product state (pose and the hands holding it), 12 language tasks, time splits |
| Format | LeRobot codebase v3.0 and v2.1 (parquet), plus the raw outputs (npz). Code: [`robots/`](../robots) |
| Size | LeRobot 6 MB (v3.0) / 7 MB (v2.1); raw outputs 3 MB |
| Not included | Contact forces. The Dex3-1 thumb rotation joint exceeds its URDF velocity limit in 11 % of the steps |
