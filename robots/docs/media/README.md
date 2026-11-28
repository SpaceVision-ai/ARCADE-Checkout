# Media

Rendered from released files with `arcade_retarget.render` (`render` extra, ffmpeg, and the robot
descriptions from `retarget/robotis_ffw_sh5/fetch_robot.sh`,
`retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh` and `retarget/unitree_g1_dex3/fetch_robot.sh`).

All three robots' videos can be reproduced from the samples in this repository: the human sample
and each robot sample contain the episodes shown (`J03826_left`, `J02562_right`). Run the commands
from `robots/`, with `RELEASE` = `../human/samples/arcade_human_sample`.

| file | command |
|---|---|
| `human_vs_robot.webp` | `python -m arcade_retarget.render --release RELEASE --retarget samples/ffw_sh5_sample/ffw_sh5 --episodes J03826_left --out hvr.mp4 --webp human_vs_robot.webp` |
| `human_vs_robot.mp4` | `python -m arcade_retarget.render --release RELEASE --retarget samples/ffw_sh5_sample/ffw_sh5 --episodes J03826_left,J02562_right --out human_vs_robot.mp4` |
| `ur10e_human_vs_robot.webp` | `python -m arcade_retarget.render --release RELEASE --retarget samples/ur10e_2f140_sample/ur10e_2f140 --episodes J02562_right --stride 2 --out hvr.mp4 --webp ur10e_human_vs_robot.webp` |
| `ur10e_human_vs_robot.mp4` | `python -m arcade_retarget.render --release RELEASE --retarget samples/ur10e_2f140_sample/ur10e_2f140 --episodes J02562_right,J03826_left --stride 2 --out ur10e_human_vs_robot.mp4` |
| `g1_human_vs_robot.webp` | `python -m arcade_retarget.render --release RELEASE --retarget samples/g1_dex3_sample/g1_dex3 --episodes J03826_left --out hvr.mp4 --webp g1_human_vs_robot.webp` |
| `g1_human_vs_robot.mp4` | `python -m arcade_retarget.render --release RELEASE --retarget samples/g1_dex3_sample/g1_dex3 --episodes J03826_left,J02562_right --out g1_human_vs_robot.mp4` |

The full ARCADE-Checkout-Human release and the full raw outputs of a robot work the same way, for
any episode they both contain. `--stride 2` shows every second step of the UR10e data (2× speed).
The second episode of the UR10e video, `J03826_left`, does not pass the UR10e robot-side check
(`arm_self_contact`); it is shown as released.
