# UR10e + Robotiq 2F-140 retargeting

The two-arm UR10e data is made **grasp first**: for every interval in which the shopper holds the
product, a parallel-jaw grasp is chosen on the product, and the arms are then moved to and with
those grasps. A gripper cannot copy a human hand, so the robot does not follow the shopper's wrist;
it follows the product.

The solver that produced these trajectories is not part of this repository. This page describes
the method; the code here reads, checks and exports the released data
(`arcade_retarget.export_lerobot`, `arcade_retarget.ur10e_2f140`, `tests/test_ur10e_sample.py`).

## Inputs

Per episode of the recording session:

* **Product:** pose trajectory, measured size and shape (box or cylinder) and mesh.
* **Holding intervals per hand** and, per frame, the human thumb, index and middle fingertips.
* **Counter extent:** shared by all episodes (counter top at `z = 0` of the counter frame).
* **Robot:** the UR10e kinematics and joint limits, and the 2F-140 geometry
  ([retarget/universal_robots_ur10e_robotiq_2f140](../retarget/universal_robots_ur10e_robotiq_2f140/README.md)). The two bases are fixed for every
  episode: 1.0 m behind the counter centre, 1.0 m apart, at counter-top height.

## Steps

1. **Product frames.** A cylinder's rotation about its own axis cannot be seen, so its axis follows
   the recording and the frame around it is carried with the least turn from frame to frame.
2. **Human grasp.** For each holding interval, the grasp point (between the thumb tip and the
   index and middle tips) and the closing direction are expressed in product coordinates (medians
   over the interval). A hold that starts while the product is already moving is moved back to the
   last still frame.
3. **Grasp planning.** For each hold, candidate grasps are sampled on the product's box or
   cylinder and scored by how close they are to the human grasp. A candidate is kept only if
   * a product resting on the counter is grasped from above, closing on two vertical faces;
   * the fingers reach at least 25 mm onto the product;
   * one UR10e wrist configuration reaches it (exact analytic IK) on every frame of the hold with
     the forearm, wrist and gripper clear of the counter.

   Hand-overs are planned for both arms together: the two grasps must keep the grippers apart
   (checked densely along the fingers). Where no pair does, one arm carries the product alone or
   puts it down for the other arm to pick up. A regrasp needs the other arm holding, and every
   frame in which the product moves gets a hold.
4. **Candidate choice.** The best three grasps per hold are tracked (step 5); the one whose
   gripper goes least into the product is kept.
5. **Tracking.** Damped least-squares IK per arm from rest, through approach, hold and retreat,
   back to rest. Approach and retreat ride with the product; the retreat backs out from the
   release pose. Where an arm lags, the timeline is slowed and the arm tracked again.
6. **Exact holds.** While holding, the arm is placed exactly on the grasp by closed-form IK (a
   configuration clear of the counter); between holds it moves in joint space. An open gripper
   opens 60 mm wider than the product.
7. **Two arms.** Outside the guarded grasp frames, a barrier QP keeps the arm links 2 cm apart, the
   grippers 1 cm apart, every link and a free gripper 3 cm above the counter, and a free gripper
   1.5 cm off the product the other arm holds. Each episode is then re-timed so that no joint
   exceeds the UR10e speed limits (shoulder 120°/s, elbow and wrists 180°/s), and the barriers
   run again on the re-timed motion.
8. **Product path.** The product moves only while a gripper holds it; a product let go in the air
   is lowered onto the counter, and a regrasp takes it where it is.

## Robot-side check

An episode is released only if none of these reaches its limit (`run` = consecutive steps; all
contact checks use the robot meshes):

| check | rejected when |
|---|---|
| hold without a robot | a holding interval that no arm performs |
| unheld motion | the product moves more than 3 mm per frame with no gripper holding it, 3 in a row |
| hovering | the product hangs in the air with no gripper holding it, 3 in a row |
| product shift | the product is moved more than 50 mm from the path its grasps were planned on |
| counter | a robot link or gripper more than 10 mm below the counter top, 3 in a row |
| arms | the two arms' meshes touch, 3 steps |
| grippers | the two grippers within 4 mm, 3 in a row |
| gripper in product | more than 5 mm inside the product while holding, approaching or retreating, 3 in a row |
| speed | a joint over the UR10e speed limit, 3 in a row |

Released: the episodes in which the shopper uses both hands, that pass the check and that are in
the ARCADE-Checkout-Human release: **45**.

## Quality figures (45 episodes)

| | result |
|---|---|
| episodes | 45: 28 passes from one arm to the other, 3 held with both arms, 14 done with one arm; 5 products |
| steps | 42,087 at 20 fps (35 min); 611 to 1,843 per episode |
| speed | median 3.7 robot steps per human frame (2.5 to 5.9 per episode), 6.5 while a gripper holds the product: the robot is slower than the shopper |
| joint limits | none of the 589,218 joint samples is beyond the URDF limits; grippers within `finger_joint` 0 to 0.648 |
| joint speed | at most 82 % of the UR10e limit (median episode 38 %) |
| arm and gripper contact | no step in which the arm meshes touch or the grippers come within 4 mm |
| counter | the lowest robot point over the counter is 8.5 mm below the counter top (single steps); never more than 10 mm for 3 steps |
| gripper in the product while holding | at most 7.9 mm (median episode 0.5 mm) |
| product | moves only while a gripper holds it; moved at most 1 mm from the path its grasps were planned on |
| robot model | forward kinematics on the upstream URDF reproduces the recorded gripper poses to 0.0002 mm and 0.00003° |

Not included: contact forces and physics validation. Joint accelerations are not limited. The
trajectories have not been run on a robot.
