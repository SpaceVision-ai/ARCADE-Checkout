"""Default locations: robot description and shipped configuration."""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PACKAGE_DIR)
CONFIG_DIR = os.path.join(PACKAGE_DIR, "configs")

#: where retarget/robotis_ffw_sh5/fetch_robot.sh puts the ROBOTIS description (override with ARCADE_FFW_DIR)
ROBOT_DIR = os.environ.get("ARCADE_FFW_DIR", os.path.join(REPO_ROOT, "retarget", "robotis_ffw_sh5", "ai_worker"))
URDF_REL = "ffw_description/urdf/ffw_sh5_rev1_follower/ffw_sh5_follower.urdf"
DEFAULT_URDF = os.path.join(ROBOT_DIR, URDF_REL)
DEFAULT_MESH_ROOT = ROBOT_DIR.rstrip("/") + "/"


def counter_config(spec: str, session: Optional[str]) -> Optional[Dict]:
    """Counter extent for the retargeting.

    spec: 'auto'    -> the shipped config for this session if there is one, else None
          'release' -> None (the caller computes it from the release)
          a path    -> that JSON file ({"counter": {...}} or the dict itself)
    """
    if spec == "release":
        return None
    if spec == "auto":
        p = os.path.join(CONFIG_DIR, f"counter_{session}.json")
        if not os.path.exists(p):
            return None
    else:
        p = spec
    d = json.load(open(p))
    return d.get("counter", d)
