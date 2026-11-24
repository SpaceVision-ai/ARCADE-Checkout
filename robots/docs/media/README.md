# Media

Rendered from released files with `arcade_retarget.render` (`render` extra, ffmpeg, and the
robot description from `retarget/robotis_ffw_sh5/fetch_robot.sh`). `RELEASE` is the ARCADE-Checkout-Human release and
`PREFIX` the retargeting outputs.

| file | command |
|---|---|
| `human_vs_robot.webp` | `python -m arcade_retarget.render --release RELEASE --retarget PREFIX --episodes J03826_left --out hvr.mp4 --webp human_vs_robot.webp` |
| `human_vs_robot.mp4` | `python -m arcade_retarget.render --release RELEASE --retarget PREFIX --episodes J03826_left,J02562_right --out human_vs_robot.mp4` |
| `ur10e_human_vs_robot.webp` | `python -m arcade_retarget.render --release RELEASE --retarget samples/ur10e_2f140_sample/ur10e_2f140 --episodes J05489_left --stride 2 --out hvr.mp4 --webp ur10e_human_vs_robot.webp` |
| `ur10e_human_vs_robot.mp4` | `python -m arcade_retarget.render --release RELEASE --retarget samples/ur10e_2f140_sample/ur10e_2f140 --episodes J05489_left,J01160_right --stride 2 --out ur10e_human_vs_robot.mp4` |
| `g1_human_vs_robot.webp` | `python -m arcade_retarget.render --release RELEASE --retarget samples/g1_dex3_sample/g1_dex3 --episodes J02771_right --out hvr.mp4 --webp g1_human_vs_robot.webp` |
| `g1_human_vs_robot.mp4` | `python -m arcade_retarget.render --release RELEASE --retarget samples/g1_dex3_sample/g1_dex3 --episodes J02771_right,J08320_left --out g1_human_vs_robot.mp4` |

Both FFW-SH5 episodes are in the samples, so `--release ../human/samples/arcade_human_sample --retarget samples/ffw_sh5_sample/ffw_sh5`
reproduces them. The UR10e and G1 videos need the full ARCADE-Checkout-Human release for the human panel, and the robot
descriptions from `retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh` and `retarget/unitree_g1_dex3/fetch_robot.sh`.
