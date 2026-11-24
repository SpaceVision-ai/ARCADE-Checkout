#!/usr/bin/env bash
# Fetch the UR10e and Robotiq 2F-140 descriptions used by the ARCADE UR10e data, pinned to fixed commits,
# and build the two-arm URDF (retarget/universal_robots_ur10e_robotiq_2f140/ur10e_2f140_dual.urdf).
#   UR10e:  https://github.com/UniversalRobots/Universal_Robots_ROS2_Description (BSD-3-Clause)
#   2F-140: https://github.com/ros-industrial-attic/robotiq, robotiq_2f_140_gripper_visualization (BSD-2-Clause)
#
#   bash retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh [DEST]      (default: retarget/universal_robots_ur10e_robotiq_2f140/upstream, about 30 MB)
#
# The URDF step needs Python with arcade_retarget and xacro installed (pip install -e ".[robot]").
# Mesh paths in the URDF are package://ur_description/... and package://robotiq_2f_140_gripper_visualization/...;
# their roots are DEST and DEST/robotiq (arcade_retarget.ur10e_2f140.package_dirs()).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${1:-$HERE/upstream}
UR_REPO=https://github.com/UniversalRobots/Universal_Robots_ROS2_Description.git
UR_COMMIT=0eb1a861f7772fceb38510d90fa2f98ec668070c
RQ_REPO=https://github.com/ros-industrial-attic/robotiq.git
RQ_COMMIT=45196f6558fe8ba9d89bc8a105396c68c3e7e892
mkdir -p "$DEST"

fetch() {   # repo commit dir sparse-paths...
  local repo=$1 commit=$2 dir=$3; shift 3
  [ -d "$dir/.git" ] || git clone --quiet --filter=blob:none --no-checkout "$repo" "$dir"
  git -C "$dir" sparse-checkout init --cone
  git -C "$dir" sparse-checkout set "$@"
  git -C "$dir" fetch --quiet origin "$commit"
  git -C "$dir" checkout --quiet "$commit"
}
fetch "$UR_REPO" "$UR_COMMIT" "$DEST/ur_description" urdf config meshes/ur10e
fetch "$RQ_REPO" "$RQ_COMMIT" "$DEST/robotiq" robotiq_2f_140_gripper_visualization

PY=${PYTHON:-python}
"$PY" -m arcade_retarget.ur10e_2f140 urdf --upstream "$DEST" --out "$HERE/ur10e_2f140_dual.urdf"
echo "package roots: $DEST  $DEST/robotiq"
