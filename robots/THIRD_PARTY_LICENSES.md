# Third-party components

| component | version | license | used as |
|---|---|---|---|
| [ROBOTIS AI Worker description](https://github.com/ROBOTIS-GIT/ai_worker) (`ffw_description`: URDF, meshes, MJCF) | commit `9bc7f7b` | Apache-2.0 | fetched at install time by `robots/ffw_sh5/fetch_robot.sh`, not redistributed |
| [Universal Robots ROS2 description](https://github.com/UniversalRobots/Universal_Robots_ROS2_Description) (`ur_description`: xacro, config, UR10e meshes) | commit `0eb1a86` | BSD-3-Clause | fetched by `robots/ur10e_2f140/fetch_robot.sh`, not redistributed |
| [ROS-Industrial Robotiq](https://github.com/ros-industrial-attic/robotiq) (`robotiq_2f_140_gripper_visualization`: xacro, meshes) | commit `45196f6` | BSD-2-Clause | fetched by `robots/ur10e_2f140/fetch_robot.sh`, not redistributed |
| [Unitree ROS description](https://github.com/unitreerobotics/unitree_ros) (`robots/g1_description`: G1 + Dex3-1 URDF, MJCF, meshes) | commit `157ff95` | BSD-3-Clause | fetched by `robots/g1_dex3/fetch_robot.sh`, not redistributed |
| [xacro](https://github.com/ros/xacro) | ≥ 2 | BSD-3-Clause | expands the fetched UR10e and 2F-140 descriptions (optional, `robot` extra) |
| [Pinocchio](https://github.com/stack-of-tasks/pinocchio) (`pin`) | ≥ 4.1 | BSD-2-Clause | kinematics (optional, `solver` extra) |
| [Pink](https://github.com/stephane-caron/pink) (`pin-pink`) | ≥ 4.3 | Apache-2.0 | differential IK (optional, `solver` extra) |
| [qpsolvers](https://github.com/qpsolvers/qpsolvers) / [quadprog](https://github.com/quadprog/quadprog) | ≥ 4.0 / ≥ 0.1.12 | LGPL-3.0 / GPL-2.0-or-later | QP backend of the IK (optional, `solver` extra; not needed to use the data) |
| [MuJoCo](https://github.com/google-deepmind/mujoco) | ≥ 3.3.3 | Apache-2.0 | preview rendering (optional, `render` extra) |
| [LeRobot](https://github.com/huggingface/lerobot) dataset layout | codebase v2.1 and v3.0 | Apache-2.0 | output format (no code vendored; v3.0 is produced with LeRobot's converter) |

## Robot images and videos

The robot images and videos in this repository (the `*_human_vs_robot.*` files in [`docs/media`](docs/media), one of
them also at the top of the repository README) are rendered from the fetched robot descriptions above. The robot meshes in them stay under their own licenses, not under this repository's CC BY-NC 4.0. The license
texts, copied from the upstream repositories at the pinned commits, are in [`licenses/`](licenses):

| robot in the renders | source | license |
|---|---|---|
| ROBOTIS FFW-SH5 | ROBOTIS AI Worker description | [Apache-2.0](licenses/ROBOTIS-ai_worker-Apache-2.0.txt) |
| UR10e | Universal Robots ROS2 description | [BSD-3-Clause](licenses/UniversalRobots-ur_description-BSD-3-Clause.txt) |
| Robotiq 2F-140 | ROS-Industrial Robotiq, Copyright (c) 2013, ROS-Industrial | [BSD-2-Clause](licenses/ROS-Industrial-robotiq-BSD-2-Clause.txt) |
| Unitree G1 + Dex3-1 | Unitree ROS description, Copyright (c) 2016-2022 HangZhou YuShu TECHNOLOGY CO.,LTD. ("Unitree Robotics") | [BSD-3-Clause](licenses/Unitree-unitree_ros-BSD-3-Clause.txt) |
