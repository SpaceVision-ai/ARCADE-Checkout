# Two UR10e arms with Robotiq 2F-140 grippers

The second retargeting target is a fixed two-arm cell:

* two Universal Robots **UR10e** arms (6 joints each) on pedestals at counter-top height, on the
  shopper's side of the counter, 1.0 m apart: one to the left and one to the right of the shopper's
  position;
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

The bases are 1.0 m behind the counter centre and 1.0 m apart, at counter-top height. The released
raw outputs record the same base poses and mount (`ur10e_2f140_ik.json -> bases`, `mount`), and the
LeRobot export copies them to `meta/arcade.json`.

## Gripper

The state holds each gripper's `finger_joint` in radians: `0` is fully open. The values belong to
the 2F-140 model the retargeting was made with (144 mm open, closed at about 0.77 rad), which is
**not** the URDF built here. What a value means is the opening, the gap between the inner pads; the
config holds it as a table against `finger_joint`:

```python
from arcade_retarget.ur10e_2f140 import gripper_gap, urdf_finger_joint
gripper_gap(0.294)          # 0.0907 m: the opening this value means
urdf_finger_joint(0.294)    # 0.228 rad: the same opening on the URDF built here
```

The upstream URDF moves the inner fingers through fixed `<mimic>` ratios and has a different
linkage: it opens to 128 mm and is closed at its upper limit `0.7`. At the same `finger_joint` its
pads are 12 to 16 mm closer than the data means (6 to 8 mm per side), so a released value applied
to this URDF as it is puts the pads inside the product. Convert through the opening
(`urdf_finger_joint`; the config holds the URDF's own table, `urdf_pad_gap_m`). The preview renderer
does. On another 2F-140 model or on the real gripper, command the opening from `gripper_gap`.

## Check

On the fetched URDF, forward kinematics of the released joint positions puts both gripper base
frames where the raw outputs record them (`<arm>__gripper_T`), and so does the MuJoCo model that
the preview renderer loads from the same URDF. `tests/test_ur10e_sample.py` runs both checks on the
sample (tolerance 0.01 mm), and also checks that every joint value is within the URDF limits.
