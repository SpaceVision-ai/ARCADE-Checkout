#!/usr/bin/env bash
# Fetch the Unitree G1 (29 DoF) + Dex3-1 description used by the ARCADE G1 data, pinned to a fixed commit.
#   https://github.com/unitreerobotics/unitree_ros  robots/g1_description  (BSD-3-Clause)
#
#   bash retarget/unitree_g1_dex3/fetch_robot.sh [DEST]      (default: retarget/unitree_g1_dex3/upstream, about 160 MB)
#
# Only g1_29dof_with_hand_rev_1_0.urdf / .xml and their meshes are checked out. The URDF is what the
# retargeting used (Pinocchio, free-flyer pelvis); the MJCF is what the preview renderer loads.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${1:-$HERE/upstream}
REPO=https://github.com/unitreerobotics/unitree_ros.git
COMMIT=157ff950351e5f535e03c5d85a16b7d594b3dbcc
[ -d "$DEST/.git" ] || git clone --quiet --filter=blob:none --no-checkout "$REPO" "$DEST"
git -C "$DEST" sparse-checkout init --no-cone
git -C "$DEST" sparse-checkout set /LICENSE /robots/g1_description/meshes/ \
  /robots/g1_description/g1_29dof_with_hand_rev_1_0.urdf /robots/g1_description/g1_29dof_with_hand_rev_1_0.xml
git -C "$DEST" fetch --quiet origin "$COMMIT"
git -C "$DEST" checkout --quiet "$COMMIT"
echo "$DEST/robots/g1_description/g1_29dof_with_hand_rev_1_0.urdf"
