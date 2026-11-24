# Two UR10e arms with Robotiq 2F-140 grippers

The second retargeting target is a fixed two-arm cell:

* two Universal Robots **UR10e** arms (6 joints each) on pedestals at counter-top height, on the
  shopper's side of the counter, 1.0 m apart;
* a Robotiq **2F-140** parallel gripper on each arm, mounted directly on the tool flange.

The robot descriptions are **not vendored** here. They are fetched from upstream at fixed commits:

| | repository | commit | license |
|---|---|---|---|
| UR10e | <https://github.com/UniversalRobots/Universal_Robots_ROS2_Description> (`urdf/ur.urdf.xacro`, `ur_type:=ur10e`) | `0eb1a861f7772fceb38510d90fa2f98ec668070c` | BSD-3-Clause |
| 2F-140 | <https://github.com/ros-industrial-attic/robotiq> (`robotiq_2f_140_gripper_visualization/urdf/robotiq_arg2f_140_model.xacro`) | `45196f6558fe8ba9d89bc8a105396c68c3e7e892` | BSD-2-Clause |

```bash
pip install -e ".[robot]"                     # xacro, to expand the upstream files without ROS
bash retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh        # -> retarget/universal_robots_ur10e_robotiq_2f140/upstream/ (about 18 MB)
                                              #    and retarget/universal_robots_ur10e_robotiq_2f140/ur10e_2f140_dual.urdf
```

The script clones the two description folders, expands both xacro files and joins two arms and two
grippers into one URDF (`python -m arcade_retarget.ur10e_2f140 urdf`). Its root link `world` is the
robot world of the dataset (floor `z = 0`, counter top `z = 0.80 m`), and its joint names are the
dataset's state names: `left_shoulder_pan_joint` … `left_wrist_3_joint`, `right_…`,
`left_finger_joint`, `right_finger_joint`. The 2F-140's other finger joints follow `finger_joint`
through the upstream `<mimic>` tags. Mesh paths stay `package://ur_description/…` and
`package://robotiq_2f_140_gripper_visualization/…`; their roots are `upstream/` and
`upstream/robotiq/` (`arcade_retarget.ur10e_2f140.package_dirs()`).

## Layout

From [`arcade_retarget/configs/ur10e_2f140.json`](../../arcade_retarget/configs/ur10e_2f140.json),
robot world frame (`x` across the counter, `y` the shopper's left, `z` up, metres):

| | value |
|---|---|
| left arm `base_link` | `(-1.2373, 0.3560, 0.80)`, no rotation |
| right arm `base_link` | `(-1.2373, -0.6440, 0.80)`, no rotation |
| gripper mount | `tool0` → `robotiq_arg2f_base_link`: no offset, −90° about the tool `z` axis |
| rest pose (both arms) | upper arm up, forearm and gripper level toward the counter (`rest_q` in the config) |

The bases are 1.0 m behind the counter centre and 1.0 m apart, at counter-top height.

## Gripper

The state holds each gripper's `finger_joint` in radians: `0` is fully open, the upstream upper
limit is `0.7`. The data uses `0` to `0.648`. The opening in metres is in the config as a table of
the inner-pad gap against `finger_joint`, measured on the simulated 2F-140 used for the
retargeting (144 mm open, closed at about 0.77 rad):

```python
from arcade_retarget.ur10e_2f140 import gripper_gap
gripper_gap(0.294)          # 0.0907 m
```

The upstream URDF moves the inner fingers through fixed `<mimic>` ratios, so its pad positions
follow a slightly different path from the simulated gripper's; use the table for the opening.

## Check

On the fetched URDF, forward kinematics of the released joint positions puts both gripper base
frames where the raw outputs record them (`<arm>__gripper_T`): largest difference **0.0002 mm and
0.00003°** over all 45 episodes (42,087 steps). The MuJoCo model that the preview renderer loads
from the same URDF agrees to 0.0004 mm. `tests/test_ur10e_sample.py` repeats both checks on the
sample, and also checks that every joint value is within the URDF limits.
