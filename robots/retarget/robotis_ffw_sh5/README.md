# ROBOTIS AI Worker FFW-SH5

The retargeting target is the ROBOTIS AI Worker **FFW-SH5** follower:

* a swerve mobile base and a lift;
* two 7-DoF arms;
* a 2-DoF head with a ZED camera;
* two HX5-D20 hands, 20 joints each.

The robot description is **not vendored** here. It is fetched from the upstream repository
at the exact commit the released trajectories were computed with:

| | |
|---|---|
| repository | <https://github.com/ROBOTIS-GIT/ai_worker> (Apache-2.0) |
| commit | `9bc7f7b93ee118f4f3f47016d2f2314c0d0895e4` (2026-09-28) |
| URDF | `ffw_description/urdf/ffw_sh5_rev1_follower/ffw_sh5_follower.urdf` (prebuilt by upstream from the xacro of the same folder) |
| meshes | `ffw_description/meshes/` (collision meshes of the hand links are used by the retargeting) |
| MuJoCo | `ffw_description/mujoco/ffw_sh5/{scene,ffw_sh5}.xml`. Used only for preview videos (`arcade_retarget.render`). Its kinematics match the URDF: over 1,000 seeded random configurations of all 60 joints within the URDF limits, the 79 shared links agree to 0.0001 mm (relative to `base_link`) |

```bash
bash retarget/robotis_ffw_sh5/fetch_robot.sh            # -> retarget/robotis_ffw_sh5/ai_worker/ (about 190 MB)
```

The script does a sparse, blob-less clone and checks the URDF's SHA-256. The renderer and the tests
find it at that default location. To keep it elsewhere, set `ARCADE_FFW_DIR=/path/to/ai_worker`.
