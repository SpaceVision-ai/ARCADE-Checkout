#!/usr/bin/env bash
# Fetch the ROBOTIS AI Worker FFW-SH5 description (URDF + meshes) used by the ARCADE retargeting.
# Upstream: https://github.com/ROBOTIS-GIT/ai_worker (Apache-2.0), pinned to the commit the
# released trajectories were computed with. Only ffw_description/{urdf,meshes,mujoco} is checked out (~190 MB).
#
#   bash retarget/robotis_ffw_sh5/fetch_robot.sh [DEST]      (default: retarget/robotis_ffw_sh5/ai_worker)
#
# Afterwards:
#   URDF      = DEST/ffw_description/urdf/ffw_sh5_rev1_follower/ffw_sh5_follower.urdf
#   mesh root = DEST/   (URDF mesh paths are package://ffw_description/...)
#   MJCF      = DEST/ffw_description/mujoco/ffw_sh5/scene.xml   (used by arcade_retarget.render)
set -euo pipefail
REPO=https://github.com/ROBOTIS-GIT/ai_worker.git
COMMIT=9bc7f7b93ee118f4f3f47016d2f2314c0d0895e4
DEST=${1:-$(cd "$(dirname "$0")" && pwd)/ai_worker}
URDF_REL=ffw_description/urdf/ffw_sh5_rev1_follower/ffw_sh5_follower.urdf
URDF_SHA256=c01b543d1d3bb9b7b71e9012ffaa163f1df74d758860a90433a1241ae964b1fb
if [ ! -d "$DEST/.git" ]; then
  git clone --filter=blob:none --no-checkout "$REPO" "$DEST"
fi
cd "$DEST"
git sparse-checkout init --cone
git sparse-checkout set ffw_description/urdf ffw_description/meshes ffw_description/mujoco
git fetch --quiet origin "$COMMIT"
git checkout --quiet "$COMMIT"
SUM=$( (sha256sum "$URDF_REL" 2>/dev/null || shasum -a 256 "$URDF_REL") | cut -d' ' -f1)   # macOS has no GNU sha256sum
[ "$SUM" = "$URDF_SHA256" ] || { echo "URDF checksum mismatch"; exit 1; }
echo "URDF:      $DEST/$URDF_REL"
echo "mesh root: $DEST/"
