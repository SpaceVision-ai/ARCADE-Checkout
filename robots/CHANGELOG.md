# Changelog

## 1.0.0

First public release of the robot datasets: the checkout episodes of the recording session on three robots.

* **ARCADE-Checkout-FFW-SH5:** 94 episodes on the ROBOTIS AI Worker FFW-SH5 (18,119 steps,
  11 tasks), with the retargeting solver that produced them (`arcade_retarget.ffw_sh5`).
* **ARCADE-Checkout-UR10e:** 45 episodes on two UR10e arms with Robotiq 2F-140 grippers
  (42,087 steps, 10 tasks).
* **ARCADE-Checkout-G1:** 80 episodes on the Unitree G1 humanoid with Dex3-1 hands (10,505 steps,
  12 tasks), each with `physics_all_held` from a MuJoCo replay of its grasps.
* LeRobot codebase v3.0 and v2.1, state only, plus the raw retargeting outputs.
* Package `arcade-retarget`: LeRobot exporter, renderer, robot models and checks.
  `retarget/*/fetch_robot.sh` fetches each robot description from its maker's repository at a
  fixed commit.
