"""Default locations: the fetched robot description and the shipped configuration."""
from __future__ import annotations

import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PACKAGE_DIR)
CONFIG_DIR = os.path.join(PACKAGE_DIR, "configs")

#: where retarget/robotis_ffw_sh5/fetch_robot.sh puts the ROBOTIS description (override with ARCADE_FFW_DIR)
ROBOT_DIR = os.environ.get("ARCADE_FFW_DIR", os.path.join(REPO_ROOT, "retarget", "robotis_ffw_sh5", "ai_worker"))
URDF_REL = "ffw_description/urdf/ffw_sh5_rev1_follower/ffw_sh5_follower.urdf"
DEFAULT_URDF = os.path.join(ROBOT_DIR, URDF_REL)
