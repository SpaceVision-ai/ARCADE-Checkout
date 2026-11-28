# Unitree G1 with Dex3-1 hands

The third retargeting target is a humanoid:

* a Unitree **G1** with 29 body joints: 6 per leg, 3 in the waist, 7 per arm;
* a Unitree **Dex3-1** hand on each arm, with three fingers and 7 joints: thumb 3, index 2, middle 2;
* a free-floating pelvis.

The robot is about 1.3 m tall. In the data it does not stand on the floor but on a step 0.35 m
high in front of the counter, so that the counter top (0.80 m above the floor) is at a working
height for its arms. The step is part of the data, not of the robot description: the fetched URDF
and MJCF hold the robot only, and the step is recorded as `stand` (height and footprint) in
`g1_dex3_ik.json` and in `meta/arcade.json` ([docs/RETARGETING_G1.md](../../docs/RETARGETING_G1.md#the-step)).
The preview renderer draws it from there.

The robot description is **not vendored** here. It is fetched from upstream at a fixed commit:

| | repository | commit | license |
|---|---|---|---|
| G1 + Dex3-1 | <https://github.com/unitreerobotics/unitree_ros> (`robots/g1_description/g1_29dof_with_hand_rev_1_0.urdf` and `.xml`) | `157ff950351e5f535e03c5d85a16b7d594b3dbcc` | BSD-3-Clause |

```bash
bash retarget/unitree_g1_dex3/fetch_robot.sh      # -> retarget/unitree_g1_dex3/upstream/ (about 160 MB)
```

The retargeting used the URDF, with a free-flyer pelvis. The preview renderer loads
the MJCF (`.xml`) of the same model.

The dataset's joint names are the URDF joint names, in URDF order:

| group | joints |
|---|---|
| legs | `left_hip_pitch_joint` … `left_ankle_roll_joint`, then `right_…` |
| waist | `waist_yaw_joint`, `waist_roll_joint`, `waist_pitch_joint` |
| left arm and hand | `left_shoulder_pitch_joint` … `left_wrist_yaw_joint`, then `left_hand_index_0_joint` … `left_hand_thumb_2_joint` |
| right arm and hand | `right_…`, in the same order |

```python
from arcade_retarget import g1_dex3 as g1
poses = g1.link_poses(state)               # 50-D dataset state (43 joints + pelvis pose) -> {link: 4x4 pose}
tips = g1.fingertips(state)                # {hand: (3, 3)} thumb, index and middle fingertip points
```

## Frames

* **Pelvis pose.** In the raw outputs the pelvis pose `[x, y, z, qx, qy, qz, qw]` is in the counter
  frame (counter top at `z = 0`). In the LeRobot state it is in the robot world (floor at `z = 0`):
  `z` is raised by `counter_h`. The feet are on the step, whose top is at `z = 0.35` in the robot
  world. The quaternion is scalar-last.
* **MuJoCo.** MuJoCo's free joint stores the quaternion scalar-first; `arcade_retarget.render.G1Scene`
  converts it.
* **Fingertip points.** Each fingertip point is 45 mm along the last link of its finger
  (`arcade_retarget.g1_dex3.tip_offset`).

## Check

Forward kinematics of the released joints and pelvis pose on the fetched URDF reproduces the
recorded fingertip points to float32 precision. The MuJoCo model agrees with the URDF to 0.002 mm.
`tests/test_g1_sample.py` runs both checks on the sample, and also checks that every joint value is
within the URDF limits.
