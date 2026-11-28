# UR10e + Robotiq 2F-140 retargeting

The dataset is made with two UR10e arms, one to the left and one to the right of the shopper's
position. It holds 110 episodes; in 65 of them both arms handle the product (a hand-over or a
both-arm hold) and in 45 one arm does everything.

The data is made **grasp first**: for every interval in which the shopper holds the product, a
parallel-jaw grasp is chosen on the product, and the arms are then moved to and with those grasps.
A gripper cannot copy a human hand, so the robot does not follow the shopper's wrist; it follows
the product.

The solver that produced these trajectories is not part of this repository. This page describes
the method; the code here reads, checks and exports the released data
(`arcade_retarget.export_lerobot`, `arcade_retarget.ur10e_2f140`, `tests/test_ur10e_sample.py`).

## Inputs

From the ARCADE-Checkout-Human 1.1.0 release, the same human data as the FFW-SH5 and G1 datasets
(`ur10e_2f140_ik.json -> release`), per episode:

* **Product:** pose trajectory, measured size and shape (box or cylinder) and mesh.
* **Holding intervals per hand** and, per frame, the human thumb, index and middle fingertips.
  During a hand-over the two hands' intervals overlap.
* **Counter footprint:** shared by all episodes (counter top at `z = 0` of the counter frame).
* **Robot:** the UR10e kinematics and joint limits, and the 2F-140 geometry
  ([retarget/universal_robots_ur10e_robotiq_2f140](../retarget/universal_robots_ur10e_robotiq_2f140/README.md)). The two bases are fixed for every
  episode: 1.0 m behind the counter centre, 1.0 m apart, at counter-top height.

The 111 episodes that pass the check of the human data are retargeted. One of them,
`J06112_left`, has no UR10e trajectory: for one of its holds the grasp planner found no grasp that
either arm can reach. So 110 episodes are released.

## Steps

1. **Product frames.** A cylinder's rotation about its own axis cannot be seen, so its axis follows
   the human data and the frame around it is carried with the least turn from frame to frame.
2. **Human grasp.** For each holding interval, the grasp point (between the thumb tip and the
   index and middle tips) and the closing direction are expressed in product coordinates. A hold
   that starts while the product is already moving is moved back to the last still frame.
3. **Grasp planning.** For each hold, candidate grasps are sampled on the product's box or
   cylinder and scored by how close they are to the human grasp. A candidate is kept only if
   * a product resting on the counter is grasped from above, closing on two vertical faces;
   * the fingers reach far enough onto the product;
   * one UR10e wrist configuration reaches it on every frame of the hold with the forearm, wrist
     and gripper clear of the counter.

   Hand-overs are planned for both arms together: the two grasps must keep the grippers apart.
   Where no pair does, one arm carries the product alone or puts it down for the other arm to pick
   up. Every frame in which the product moves gets a hold.
4. **Candidate choice.** The best candidates per hold are tracked (step 5); the one whose
   gripper goes least into the product is kept.
5. **Tracking.** Each arm goes from rest through approach, hold and retreat back to rest. Approach
   and retreat move with the product; the retreat backs out from the release pose. Nothing follows
   the human frame by frame: the arm tracks the product.
6. **Exact holds.** While holding, the arm is placed exactly on the grasp by closed-form IK, in a
   configuration that is clear of the counter and keeps the wrist and gripper 20 mm clear of the
   same arm's forearm and upper arm: where the planned configuration does not, the other wrist
   branch, then the other elbow and shoulder configurations are tried. Between holds the arm moves
   in joint space; a move that would sweep the wrist through its own forearm turns the wrist the
   other way round.
7. **Two arms.** Outside the grasp frames the arms are kept apart from each other, from the
   counter and from the product the other arm holds. This correction keeps each step of an arm close
   to its previous step, within the joint velocity limits and inside the joint ranges, so it does not
   make the arm jitter. Each arm's path is first placed on the whole turns of its joints (the same
   poses) that keep it inside the joint ranges of the URDF.
8. **Re-timing.** Each episode is re-timed toward these joint velocity and acceleration limits:

   | joint | velocity limit (deg/s) | acceleration limit (deg/s²) |
   |---|---|---|
   | `shoulder_pan_joint` | 120 | 150 |
   | `shoulder_lift_joint` | 120 | 150 |
   | `elbow_joint` | 180 | 250 |
   | `wrist_1_joint` | 180 | 300 |
   | `wrist_2_joint` | 180 | 300 |
   | `wrist_3_joint` | 180 | 300 |

   The limits are recorded in `ur10e_2f140_ik.json -> args`. In the released data joint velocities (finite differences of the samples) stay within the velocity limits at all but 1 of the 96,040 steps; accelerations exceed the acceleration values at 2.5 % of the steps, because the arm-separation pass that runs after the re-timing is not acceleration-limited.
   Smooth the trajectories or re-time them again before using them where acceleration matters.
   The re-timing makes the UR10e the slowest of the three robots; `tmap` and `source_frame` give the session frame of each step.
9. **Product path.** The product moves only while a gripper holds it; a product let go in the air
   is lowered onto the counter, and a regrasp takes it where it is. The product may therefore
   shift from the human product path, by up to 50 mm in a passing episode
   (`ur10e_2f140_obj.json -> track`).

## Robot-side check

Every released episode is labelled by an automatic check. An episode fails it when any of these
reaches its limit (`in a row` = consecutive steps; all contact checks use the robot meshes), and
the ids of the rules it fails are recorded with it (`ur10e_2f140_obj.json -> check`, `check_failed`
in the LeRobot episodes metadata).

| rule id | check | fails when |
|---|---|---|
| `no_grasp` | hold without a robot | a holding interval that no arm performs |
| `product_unheld` | unheld motion | the product moves more than 3 mm per frame with no gripper holding it, 3 in a row |
| `product_hovers` | hovering | the product hangs in the air with no gripper holding it, 3 in a row |
| `product_shift` | product shift | the product is moved more than 50 mm from the human product path |
| `counter` | counter | a robot link or gripper more than 10 mm below the counter top, 3 in a row |
| `arm_contact` | arms | the two arms' meshes touch, 3 steps |
| `arm_self_contact` | an arm with itself | the last wrist link or the gripper within 4 mm of the same arm's forearm or upper arm, 3 in a row |
| `gripper_contact` | grippers | the two grippers within 4 mm, 3 in a row |
| `gripper_in_product`, `gripper_in_product_before_grasp`, `gripper_in_product_after_release` | gripper in product | more than 5 mm inside the product while holding, while approaching or while retreating, 3 in a row |
| `joint_speed` | speed | a joint over its speed limit, 3 in a row |
| `joint_limit` | joint range | a joint outside its position range in the URDF (elbow ±π, the other joints ±2π), at any step |

Result on the 110 released episodes:

| | episodes |
|---|---|
| released | 110 |
| pass the check | 67 |
| fail the check (the `rejected` split) | 43 |
| fail `arm_self_contact` | 18 |
| fail `product_shift` | 15 |
| fail `gripper_contact` | 11 |
| fail `counter` | 8 |
| fail `no_grasp` | 7 |
| fail `gripper_in_product` | 3 |
| fail `gripper_in_product_after_release` | 2 |
| fail `product_hovers` | 2 |
| fail `joint_speed` | 1 |

An episode can fail several rules, so the rule counts add up to more than 43.

**An arm against itself.** The retargeting keeps the wrist and gripper clear of the same arm where
another arm configuration reaches the grasp (step 6). Where none does, the contact stays in the
data and the episode fails `arm_self_contact`: 18 of the 110 episodes, among them the sample
episode `J03826_left`. The distance is measured between the link surfaces of the robot model the
data was made with; the collision shapes of the fetched URDF are simplified hulls that also overlap
in poses where those surfaces are a few centimetres apart.

## Figures

| | released (110 episodes) | passing (67 episodes) |
|---|---|---|
| both arms handle the product (hand-over or both-arm hold) | 65 | 32 |
| one arm does everything | 45 | 35 |
| task kinds: `pass` / `one_arm` / `both_arms` | 60 / 45 / 5 | 29 / 35 / 3 |
| output steps at 20 fps | 96,040 | 54,678 |
| language tasks | 11 | 9 |

* **Steps per episode:** 478 / 828 / 1,625 (min / median / max).
* **Splits of the passing episodes:** train 52, val 6, test 7, with 2 boundary episodes in none
  of them.
* **Size:** raw outputs 12 MB, LeRobot 12 MB (v3.0) / 16 MB (v2.1).

Not included: contact forces. The trajectories are kinematic: no physics validation is part of
this release, and they were not executed on a robot.
