"""Unitree G1 humanoid (29 body joints) with Dex3-1 hands: names, fingertip points and the robot description.

The robot description is Unitree's ``g1_29dof_with_hand_rev_1_0`` from ``unitreerobotics/unitree_ros``
(BSD-3-Clause), fetched by ``retarget/unitree_g1_dex3/fetch_robot.sh``; it is not redistributed here. Joint names in the
data are the URDF joint names. The pelvis is a free-floating base: its pose is stored next to the joints.

Kinematics with Pinocchio (``pip install pin``)::

    from arcade_retarget import g1_dex3 as g1
    model = g1.pin_model()                      # free-flyer G1 + the fingertip frames used by the retargeting
    q = g1.pin_configuration(state)             # 50-D dataset state -> Pinocchio configuration
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

import numpy as np

from .paths import REPO_ROOT

ROBOT = "g1_dex3"
ROBOT_TYPE = "unitree_g1_dex3"
URDF_NAME = "g1_29dof_with_hand_rev_1_0"
SIDES = ("left", "right")

LEG = ["hip_pitch_joint", "hip_roll_joint", "hip_yaw_joint", "knee_joint", "ankle_pitch_joint", "ankle_roll_joint"]
WAIST = ["waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint"]
ARM = ["shoulder_pitch_joint", "shoulder_roll_joint", "shoulder_yaw_joint", "elbow_joint",
       "wrist_roll_joint", "wrist_pitch_joint", "wrist_yaw_joint"]
HAND = ["hand_index_0_joint", "hand_index_1_joint", "hand_middle_0_joint", "hand_middle_1_joint",
        "hand_thumb_0_joint", "hand_thumb_1_joint", "hand_thumb_2_joint"]
#: the 43 joints in URDF (Pinocchio) order: legs, waist, left arm and hand, right arm and hand
JOINT_NAMES = ([f"left_{j}" for j in LEG] + [f"right_{j}" for j in LEG] + WAIST
               + [f"left_{j}" for j in ARM + HAND] + [f"right_{j}" for j in ARM + HAND])
#: pelvis pose: position (m) and orientation quaternion (x, y, z, w)
PELVIS_NAMES = ["pelvis_x", "pelvis_y", "pelvis_z", "pelvis_qx", "pelvis_qy", "pelvis_qz", "pelvis_qw"]
STATE_NAMES = JOINT_NAMES + PELVIS_NAMES
GROUPS = (("left_leg", 6), ("right_leg", 6), ("waist", 3), ("left_arm", 7), ("left_hand", 7),
          ("right_arm", 7), ("right_hand", 7), ("pelvis", 7))

FINGERS = ("thumb", "index", "middle")
#: fingertip points: a point on the last link of each Dex3-1 finger, offset along the finger (m)
TIP_LINK = {"thumb": "hand_thumb_2_link", "index": "hand_index_1_link", "middle": "hand_middle_1_link"}
TIP_OFFSET = 0.045

#: where fetch_robot.sh puts the upstream description (override with ARCADE_G1_DIR)
ROBOT_DIR = os.environ.get("ARCADE_G1_DIR", os.path.join(REPO_ROOT, "retarget", "unitree_g1_dex3", "upstream"))
DESCRIPTION_DIR = os.path.join(ROBOT_DIR, "robots", "g1_description")
DEFAULT_URDF = os.path.join(DESCRIPTION_DIR, URDF_NAME + ".urdf")
DEFAULT_MJCF = os.path.join(DESCRIPTION_DIR, URDF_NAME + ".xml")


def tip_offset(side: str, finger: str) -> np.ndarray:
    """Offset of a fingertip point in its link frame (m)."""
    if finger == "thumb":
        return np.array([0.0, (-1.0 if side == "left" else 1.0) * TIP_OFFSET, 0.0])
    return np.array([TIP_OFFSET, 0.0, 0.0])


def pin_model(urdf: str = DEFAULT_URDF):
    """Pinocchio model of the G1 with a free-flyer pelvis and frames ``<side>_<finger>_tip``."""
    import pinocchio as pin
    if not os.path.exists(urdf):
        raise SystemExit(f"robot description not found ({urdf}): run bash retarget/unitree_g1_dex3/fetch_robot.sh")
    m = pin.buildModelFromUrdf(urdf, pin.JointModelFreeFlyer())
    for side in SIDES:
        for finger, link in TIP_LINK.items():
            fid = m.getFrameId(f"{side}_{link}")
            fr = m.frames[fid]
            m.addFrame(pin.Frame(f"{side}_{finger}_tip", fr.parentJoint, fid,
                                 fr.placement * pin.SE3(np.eye(3), tip_offset(side, finger)), pin.FrameType.OP_FRAME))
    return m


def pin_configuration(joints: np.ndarray, pelvis: Optional[np.ndarray] = None) -> np.ndarray:
    """Pinocchio configuration (50,) from the 43 joints and the pelvis pose [x y z qx qy qz qw],
    or from one 50-D dataset state (joints, then pelvis)."""
    x = np.asarray(joints, dtype=np.float64)
    if pelvis is None:
        x, pelvis = x[:43], x[43:50]
    return np.concatenate([np.asarray(pelvis, dtype=np.float64), x])


# --- holds and tasks ---------------------------------------------------------------------------------------

def holding_runs(holding: np.ndarray) -> List[Dict]:
    """Intervals [start, end) in output steps where each hand holds the product. holding: (n, 2) bool, left then right."""
    out = []
    for c, side in enumerate(SIDES):
        h = np.asarray(holding[:, c], bool)
        edges = np.flatnonzero(np.diff(np.r_[0, h.astype(np.int8), 0]))
        out += [dict(hand=side, start=int(a), end=int(b)) for a, b in zip(edges[::2], edges[1::2])]
    return sorted(out, key=lambda r: (r["start"], r["end"]))


def _first_last(runs: Sequence[Dict]):
    first = min(runs, key=lambda r: r["start"])["hand"]
    last = max(runs, key=lambda r: (r["end"], r["start"]))["hand"]
    return first, last


def task_kind(runs: Sequence[Dict]) -> str:
    """one_hand, pass (ends in the other hand) or both_hands (both hold it, the first one puts it down)."""
    from arcade_human.tasks import kind_of
    if not runs:
        return "one_hand"
    first, last = _first_last(runs)
    return kind_of(first, last, [r["hand"] for r in runs])


def task_sentence(shape: str, runs: Sequence[Dict]) -> str:
    """Language task of an episode from the robot's own holds (same sentences as the human data)."""
    from arcade_human.tasks import task_sentence as sentence
    if not runs:
        return sentence(shape, "right", "right", False)
    first, last = _first_last(runs)
    return sentence(shape, first, last, len({r["hand"] for r in runs}) > 1)
