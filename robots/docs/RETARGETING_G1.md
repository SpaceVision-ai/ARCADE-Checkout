# Unitree G1 + Dex3-1 retargeting

The G1 data is **whole-body**: legs, waist, arms and the two three-finger Dex3-1 hands of a Unitree G1
(29 body joints) are solved together, with the pelvis free to move. The robot stands where the shopper
stood, **on a 0.35 m step in front of the counter** ([The step](#the-step)), and keeps both feet in
place. The product keeps the path it took in the human data, and each hand is moved onto a grasp
planned on the product for every interval in which the shopper holds it.

The solver that produced these trajectories is not part of this repository. This page describes the
method and how the data was checked. The code here reads, checks and exports the released data
(`arcade_retarget.export_lerobot`, `arcade_retarget.g1_dex3`, `tests/test_g1_sample.py`).

## Inputs

From the ARCADE-Checkout-Human 1.1.0 release, the same human data as the FFW-SH5 and UR10e datasets
(`g1_dex3_ik.json -> release`), per episode:

* **Product:** pose trajectory, measured size and shape (box or cylinder), and mesh.
* **Shopper:** the holding intervals of each hand, and per frame the wrist, the thumb, index and
  middle fingertips, the shoulders, elbows and hips.
* **Counter:** the counter top (`z = 0` of the counter frame), its footprint and its near edge. The
  floor is assumed to be 0.80 m below the counter top.
* **Robot:** Unitree `g1_29dof_with_hand_rev_1_0` ([retarget/unitree_g1_dex3](../retarget/unitree_g1_dex3/README.md)).

Every episode that passes the check of the human data is retargeted and released: 111 episodes.

## The step

The G1 is about 1.3 m tall, and the counter top is 0.80 m above the floor. Standing on the floor,
the robot has the counter top at its chest and works with raised arms: its upper arm is 80° from
hanging in the median, against the shopper's 24°. The data therefore puts the robot on a step
0.35 m high in front of the counter, where the median is 39°.

* The step height was chosen once for the whole dataset; it is not tuned per episode.
* It is recorded in the data: `g1_dex3_ik.json -> stand` and `meta/arcade.json -> stand` hold the
  `height` and the footprint of the step (`x0, x1, y0, y1`, counter frame).
* Robot world: floor `z = 0`, top of the step `z = 0.35`, counter top `z = 0.80`. The feet are on
  the step, and the pelvis pose in the LeRobot state is in this frame.
* The step is part of the data, not of the robot description. A simulation or a robot cell that
  replays the trajectories needs a step of this height, or a counter 0.35 m lower.

## Steps

1. **Grasp plan.** For each hold, the Dex3-1 hand alone (wrist pose and 7 finger joints) closes on
   the product's box or cylinder in opposition: the thumb, index and middle fingertips on the surface,
   the index and middle fingers across the product from the thumb, finger pads facing the surface, and
   no hand point inside the product or below the counter top. The grasp is planned near the human
   grasp: the shopper gives the grasp centre, the side of the thumb and the wrist direction. Further
   candidates move the grasp toward the product's centre, because a three-finger pinch near one end
   of a long box twists out.
2. **Grasp choice.** The candidates are ranked with a short simulated carry: the hand is moved
   along the product's path with the product free, and candidates that keep it rank first. The
   trajectory uses the best-ranked candidate whose motion passes the robot-side check. In a
   hand-over the two grasps are chosen together and kept apart. This ranking is a planning step;
   its outcome is not released as a validation result.
3. **Holds.** A hand's hold runs from its grasp to its release. In a hand-over the two holds
   overlap: the receiving hand's hold starts when the human hand first touches the product.
4. **Product path.** The product follows the human product path. While a hand holds it, the path
   is lightly smoothed, and the change fades in and out at the ends of the hold, so the pick-up and
   set-down poses stay as in the human data. Outside holds the path is unchanged.
5. **Whole-body IK** (free-floating G1). The tasks are:
   * during a hold, the fingertips, the wrist and points on the hand follow the planned grasp as it
     moves with the product;
   * on the approach, the hand comes in from a stand-off outside the product;
   * outside holds, the fingertips follow the shopper's (smoothed);
   * both feet stay where they are, on the step;
   * the centre of mass stays inside the support area of the two soles;
   * the pelvis and torso stay upright (a weak task), plus a posture task.

   Joints keep their URDF position limits, and joint speeds are capped.
6. **Clearances.** The forearms and hands are kept away from each other and from the torso, pelvis
   and legs; the robot is kept out of the counter; the hands are kept out of the product outside
   their own holds; the pelvis, torso and knees stay behind the near edge of the counter
   (`g1_dex3_ik.json -> counter_edge`).
7. **Hand-over timing.** Shoppers pass the product while it is still moving. Around the second
   hand's grasp the timeline is slowed; everywhere else the robot keeps the human timing.

## Robot-side check

Every released episode is labelled by an automatic check. An episode fails it when any of these
holds for 3 steps in a row (all contact checks use the robot meshes), and the ids of the rules it
fails are recorded with it (`g1_dex3_obj.json -> check`, `check_failed` in the LeRobot episodes
metadata).

| rule id | check | fails when |
|---|---|---|
| `not_gripping` | grip | the shopper holds the product but the robot hand does not grip it: the thumb and a finger are not both within 25 mm of the surface, on sides at least 120° apart, with the product between them |
| `no_contact` | contact | the shopper's fingertips touch the product but the robot's do not |
| `hand_in_product`, `hand_in_product_before_grasp`, `hand_in_product_after_release` | hand in product | a hand more than 5 mm inside the product while holding, while approaching or while retreating |
| `counter` | counter | a robot link more than 10 mm inside the counter |
| `hand_contact` | hands | the forearm and hand meshes of the two arms within 4 mm of each other |
| `arm_body_contact` | arm–body | a forearm or hand mesh within 4 mm of the torso, pelvis or legs |
| `joint_speed` | speed | a joint over its speed cap |
| `balance` | balance | the centre of mass outside the support polygon of the feet |
| `foot_slide` | feet | over the whole episode: a foot moves more than 10 mm from its place |

`g1_dex3_obj.json -> check` also holds the per-episode extremes these rules are computed from
([FORMAT.md](FORMAT.md#unitree-g1--dex3-1)).

Result on the 111 released episodes:

| | episodes |
|---|---|
| released | 111 |
| pass the check | 98 |
| fail the check (the `rejected` split) | 13 |
| fail `hand_in_product` | 5 |
| fail `not_gripping` | 5 |
| fail `hand_contact` | 3 |
| fail `no_contact` | 2 |
| fail `hand_in_product_before_grasp` | 2 |
| fail `arm_body_contact` | 1 |

An episode can fail several rules, so the rule counts add up to more than 13.

## Figures

| | released (111 episodes) | passing (98 episodes) |
|---|---|---|
| task kinds: `pass` / `both_hands` / `one_hand` | 54 / 14 / 43 | 49 / 12 / 37 |
| output steps at 20 fps | 14,104 | 12,665 |

* **Language tasks:** 12, from the robot's own holds.
* **Steps per episode:** 60 / 124 / 234 (min / median / max).
* **Splits of the passing episodes:** train 73, val 10, test 12, with 3 boundary episodes in none
  of them.
* **Size:** raw outputs 5 MB, LeRobot 8 MB (v3.0) / 10 MB (v2.1).

Not included: contact forces, and walking (the robot never steps). The product follows the human
product path, not the robot hands. In a hand-over, two position-controlled hands hold one rigid
product; a real hand-over needs force control, which the IK does not model. The trajectories are
kinematic: no physics validation is part of this release, and they were not executed on a robot.
