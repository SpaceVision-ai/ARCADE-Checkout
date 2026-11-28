# FFW-SH5 retargeting

This page describes how the released FFW-SH5 trajectories were produced and checked. **The solver that
produced them is not part of this repository**; the repository reads, checks, exports and renders the
released files.

## Inputs

From the ARCADE-Checkout-Human 1.1.0 release, per episode (the raw outputs record the release in
`PREFIX_ik.json -> release`). The UR10e and G1 data are made from the same release, so all three
robots share the episodes, the hand and product poses, the holding labels and the counter.

* **Shopper motion:** shoulders, elbows and both hands (21 landmarks each).
* **Product:** pose trajectory, measured size and mesh. The mesh is turned into a
  signed distance field for clearance checks.
* **Holding intervals per hand:** `interaction/*/holding`, from the hand's grasp to its release.
  During a hand-over both hands hold.
* **Carrying intervals per hand:** `interaction/*/carrying`, the hand the product moves with, one
  at a time.
* **Counter footprint:** shared by all episodes, a box around every resting product position of the
  recording session (`PREFIX_ik.json -> counter`).

Every episode that passes the check of the human data is retargeted and released: 111 episodes.

From the robot description ([`retarget/robotis_ffw_sh5`](../retarget/robotis_ffw_sh5/README.md)):

* the FFW-SH5 URDF;
* the collision meshes of the HX5-D20 hand links.

## Steps

1. **Window.** The robot follows the shopper only inside one window shared by both hands, from
   shortly before the first grasp to shortly after the last release.
   Outside it, the arms and fingers stay at a home pose.
2. **Hand retargeting.** For every frame in the window, the robot hand frame and its 20 finger
   joints are fitted to the human hand by least squares:
   * fingertip positions first, then phalanx and palm directions;
   * within the HX5-D20 joint limits;
   * without finger self-collision;
   * with frame-to-frame continuity.
3. **Grasp.** For every hold, the fingers are solved onto the product surface, with the thumb
   opposite the fingers, starting from the human finger pose, instead of only following the human
   fingertips. A hold for which no grasp is found in which thumb and fingers reach the product
   surface without going into it fails the rule `grasp_contact`.
4. **Carry.** While the product is carried, the hand keeps that grasp: the product is attached to
   the robot hand and does not move inside it. During a hand-over both hands hold the product, and
   it stays attached to one hand at a time (`carrying`, `obj_carrier`).
5. **Release.** At a release the fingers peel off the product and the hand lifts away before it
   retreats.
6. **Clearance.** Before the first grasp and after the last release only the wrist path is
   shifted, with the hand shape unchanged, so the hand mesh clears the product and the counter.
   The shift fades out just before the grasp and is zero from the first grasp to the last release.
   It is stored as `<hand>__avoid`. These are the
   [phases](../../README.md#what-happens-in-an-episode) 0, 1 and 3 of each hand.
7. **Idle hand.** A hand that is not holding and is not about to grasp moves toward a rest
   pose beside the body when it comes close to the working hand or arm
   (`<hand>__yield`).
8. **Whole-body differential IK.** Variables: the planar swerve base and both 7-DoF arms; the lift
   stays fixed. The hands follow their targets while the elbows follow the shopper's, within the
   joint position and velocity limits, and the arms keep clear of the torso, the counter edge and
   each other.
9. **Re-timing.** Where the arm cannot follow at the shopper's speed, the timeline is slowed and
   solved again. This produces the `tmap` time map.
10. **Home transitions.** Between home and the edge of the window the arms move in a smooth
    joint-space transition that stays clear of the counter, the product and the other hand. The
    base follows slowly and returns to its start pose after the window.
11. **Head.** The head aims the ZED camera at the working hand.
12. **Product.** The product is moved onto the output steps. While carried it is attached to the
    robot hand (`obj_carrier` says which one). After a release it settles onto its nearest
    stable face.

Contact forces are not modelled. The trajectories are kinematic: no physics validation is part of
this release, and they were not executed on a robot. What a kinematic retargeting does and does not
determine about a five-finger grasp: [Hands and grippers](../README.md#hands-and-grippers).

## Robot-side check

Every released episode is labelled by an automatic check of the robot motion, computed with the
robot's collision meshes and the product mesh. No episode is left out: an episode fails the check
when any of these hold, and the ids of the rules it fails are recorded with it
(`PREFIX_obj.json -> episodes[<episode_id>] -> check`, `check_failed` in the LeRobot episodes
metadata).

| rule id | check | condition |
|---|---|---|
| `finger_self_collision` | finger self-collision | fingers of one hand interpenetrate by more than 3 mm for 3 or more consecutive steps |
| `finger_speed` | finger speed | a finger joint changes by more than 25° in one step |
| `touch_before_grasp` | touch before the grasp | a hand is more than 5 mm inside the product for 3+ steps up to 6 frames before the episode's first grasp (phase 0) |
| `touch_after_release` | touch after the release | a hand is more than 5 mm inside the product for 3+ steps from 3 frames after its last release |
| `counter` | counter | a hand or wrist is more than 10 mm below the counter top for 3+ steps |
| `hand_overlap` | hand overlap | the two hands overlap by more than 5 mm for 3+ steps |
| `idle_hand` | idle hand | the hand that never holds the product comes within 3 mm of the working hand or arm for 3+ steps |
| `arm_branch` | arm branch | an arm joint turns by more than 90° while the wrist barely moves |
| `product_in_hand` | product in hand | the carried product is more than 30 mm from the robot hand mesh while it moves, for 3+ steps |
| `product_path` | product path | the carried product is more than 30 mm from the human product path for 5+ steps |
| `grasp_contact` | grasp contact | no grasp was found in which thumb and fingers reach the product surface without going into it |

Result on the 111 released episodes:

| | episodes |
|---|---|
| released | 111 |
| pass the check | 83 |
| fail the check (the `rejected` split) | 28 |
| fail `product_path` | 16 |
| fail `arm_branch` | 7 |
| fail `hand_overlap` | 7 |
| fail `idle_hand` | 3 |
| fail `touch_after_release` | 2 |
| fail `grasp_contact` | 1 |

An episode can fail several rules, so the rule counts add up to more than 28. The time splits of
the passing episodes are train 61, val 10 and test 9, with 3 boundary episodes in none of them.

## Figures

| | released (111 episodes) | passing (83 episodes) |
|---|---|---|
| output steps at 20 fps | 27,024 | 18,954 |
| language tasks | 12 | 11 |

* **Steps per episode:** 151 / 230 / 432 (min / median / max).
* **Speed:** the timeline is slowed where the arm cannot follow; `source_frame` maps every step to
  its human frame.
* **Product:** a passing episode has no run of 5 or more steps in which the carried product is
  more than 30 mm from the human product path (rule `product_path`). The per-episode deviations
  are in `PREFIX_obj.json -> track`.
* **Size:** raw outputs 12 MB, LeRobot 14 MB (v3.0) / 18 MB (v2.1).
