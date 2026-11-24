# Unitree G1 + Dex3-1 retargeting

The G1 data is **whole-body**: legs, waist, arms and the two three-finger Dex3-1 hands of a Unitree G1
(29 body joints) are solved together, with the pelvis free to move. The robot stands where the shopper
stood and keeps both feet in place. The product keeps the path it took in the recording, and each hand
is moved onto a grasp planned on the product for every interval in which the shopper holds it.

The solver that produced these trajectories is not part of this repository. This page describes the
method and how the data was checked. The code here reads, checks and exports the released data
(`arcade_retarget.export_lerobot`, `arcade_retarget.g1_dex3`, `tests/test_g1_sample.py`).

## Inputs

Per episode of the recording session:

* **Product:** pose trajectory, measured size and shape (box or cylinder), and mesh.
* **Shopper:** the holding intervals of each hand, and per frame the wrist, the thumb, index and
  middle fingertips, the shoulders, elbows and hips.
* **Counter:** the counter top (`z = 0` of the counter frame) and its near edge, inferred from where
  products rest. The floor is assumed to be 0.80 m below the counter top.
* **Robot:** Unitree `g1_29dof_with_hand_rev_1_0` ([retarget/unitree_g1_dex3](../retarget/unitree_g1_dex3/README.md)).

## Steps

1. **Grasp plan.** For each hold, the Dex3-1 hand alone (wrist pose and 7 finger joints) closes on
   the product's box or cylinder in opposition: the thumb, index and middle fingertips on the surface,
   the index and middle fingers across the product from the thumb, finger pads facing the surface, and
   no hand point inside the product or below the counter top. The shopper gives the grasp centre, the
   side of the thumb and the wrist direction. Further candidates move the grasp toward the product's
   centre, because a three-finger pinch near one end of a long box twists out.
2. **Grasp choice in physics.** Each candidate is tried in MuJoCo with the hand carried along the
   product's recorded path. Candidates that are kinematically acceptable come first, then those that
   hold the product, then by how much of the hold they carry it. The whole-body IK tries them in that
   order. In a hand-over the two grasps are chosen together and kept at least 15 mm apart.
3. **Product path.** While a hand holds the product, its recorded path is smoothed (Savitzky-Golay,
   order 2, 9 frames). The change fades in and out over the first and last 4 frames of the hold, so
   the pick-up and set-down poses stay as recorded. Over the released episodes the held product moves
   3.8 / 12.5 / 28.5 mm (p50 / p90 / p99) and 3.2° (p90) from the recording; outside holds it is
   unchanged.
4. **Whole-body IK** (Pink, free-floating G1). The tasks are:
   * during a hold, the fingertips, the wrist and points on the hand follow the planned grasp as it
     rides with the product;
   * on the approach, the hand comes in from a stand-off outside the product;
   * outside holds, the fingertips follow the shopper's (smoothed);
   * both feet stay where they are;
   * the centre of mass stays inside the support box of the two soles;
   * the pelvis and torso stay upright (a weak task), plus a posture task.

   Joints keep their URDF position limits. Joint speed is capped at 3 rad/s for the legs, waist and
   arms and at 5 rad/s for the hand joints.
5. **Collision barriers.** Each barrier keeps two sets of meshes apart:

   | barrier | keeps |
   |---|---|
   | hand–hand | each forearm and hand 12 mm from the other |
   | arm–body | each forearm and hand 12 mm from the torso, pelvis and legs |
   | counter | the robot no more than 5 mm into the counter |
   | product | the hands out of the product outside their own holds |
   | counter edge | the pelvis, torso and knees behind the near edge |

   Where the barrier QP is infeasible, the step is retried with the barriers relaxed one group at a time.
6. **Stance.** The robot stands at the shopper's hips. Per episode, three stances (at the hips, and
   10 cm to either side along the counter) and the top three grasp candidates are tracked. The check
   below keeps the best combination.
7. **Hand-over timing.** Shoppers pass the product while it is still moving. Around the second
   hand's grasp, the timeline is slowed so the product moves at most 0.4 m/s along its own path. This
   applies in 40 of the 80 episodes, at up to 1.8 robot steps per human frame.

## Robot-side check

An episode is rejected when any of these holds for 3 steps in a row. All contact checks use the
robot meshes.

| check | rejected when |
|---|---|
| grip | the shopper holds the product but the robot hand does not grip it: the thumb and a finger are not both within 25 mm of the surface, on sides at least 120° apart, with the product between them |
| contact | the shopper's fingertips touch the product but the robot's do not |
| hand in product | a hand more than 5 mm inside the product while holding, approaching or retreating |
| counter | a robot link more than 10 mm inside the counter |
| hands, arm–body | the forearm and hand meshes within 4 mm of each other, or of the torso, pelvis or legs |
| speed | a joint over its speed cap |
| balance | the centre of mass outside the support polygon of the feet |
| foot slide | a foot slides more than 5 mm in one step |

One more check applies to the whole episode: no foot may move more than 10 mm from its place.

Released: **80** episodes. These are the ones that pass every check and are also in the
ARCADE-Checkout-Human release.

## Physics replay

Each hold is replayed on its own in MuJoCo:

* the pelvis and both wrists follow the released trajectory;
* the body joints follow the released angles through soft servos with gravity compensation;
* the Dex3-1 fingers are torque-limited position servos, closed slightly past the planned grasp;
* the product is a free box or cylinder of its measured size, 0.3 kg, friction 1 (assumed, not
  measured), starting from its recorded pose.

While the product is in the air, the hold is judged as follows:

* **lost:** fewer than two hand links touch the product for 3 steps;
* **slipped:** the product moves more than 60 mm in the hand;
* **held:** otherwise.

| | result |
|---|---|
| holds | 136: 93 held, 5 slipped, 38 lost |
| episodes held in every hold (`physics_all_held`) | **45 of 80**: 27 of 32 one-hand, 15 of 38 passes, 3 of 10 held with both hands |

Most losses happen in hand-overs. There, two position-controlled hands hold one rigid product. A
real hand-over needs force control, and neither the IK nor the replay models it.

`physics_all_held` is in `meta/episodes.jsonl` (v2.1) and the episodes table (v3.0). The per-hold
verdicts are in the raw `g1_dex3_obj.json`. Filter on them to train only on episodes whose grasps
also carried the product in simulation.

## Quality figures (80 episodes)

| | result |
|---|---|
| episodes | 80: 38 passes from one hand to the other, 10 held with both hands, 32 one-hand; 5 products |
| steps | 10,505 at 20 fps (8.8 min), 64 to 222 per episode |
| speed | the robot follows the shopper's clock (median 1.03 robot steps per human frame); 40 episodes are slowed around hand-over grabs, at up to 1.8 |
| stance | both feet stay in place in every episode (no steps; the largest foot movement is 2.3 mm); the pelvis moves at most 1.1 m/s |
| balance | the centre of mass is inside the support polygon of both feet at every step (smallest margin 8.8 mm, median episode 30 mm). The check is quasi-static |
| joint limits | none of the 451,715 joint samples is beyond the URDF limits; 5.2 % are within 0.05 rad of one |
| joint speed | legs, waist and arms reach at most 44 % of their URDF velocity limits. The Dex3-1 thumb rotation joint (`*_hand_thumb_0_joint`, URDF 3.14 rad/s) reaches 5.1 rad/s and is above its URDF limit in 11 % of the steps |
| grip | the robot hand grips the product in 99.9 % of its holding steps |
| hand in product | more than 5 mm inside the held product in 12 of 8,093 holding steps (never 3 in a row); at most 21 mm |
| hands, arms, body | the hands come within 4 mm of each other in 14 steps (never 3 in a row); the arms stay at least 7.7 mm from the body |
| counter | more than 10 mm into the counter in 4 steps; at most 24 mm |
| physics | 45 of 80 episodes keep the product in every hold ([above](#physics-replay)) |
| robot model | forward kinematics of the released joints on the upstream URDF reproduces the recorded fingertip points to float32 precision; the MuJoCo model (Unitree's MJCF) agrees with the URDF to 0.002 mm |

Not included: contact forces, and walking (the robot never steps). The product follows its recorded
path, not the robot hands; only the physics replay tests whether the grasps would carry it. Arm joints
are capped at 3 rad/s, so where the shopper moves faster, a free arm lags and then catches up. The
trajectories have not been run on a robot.
