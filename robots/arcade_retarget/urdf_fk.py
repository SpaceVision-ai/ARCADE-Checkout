"""Forward kinematics of a URDF: link poses for given joint positions, with numpy only.

    from arcade_retarget.urdf_fk import Chain
    chain = Chain("robot.urdf")
    poses = chain.link_poses({"left_elbow_joint": 0.4})   # {link name: 4x4 pose in the root link's frame}

Joints that are not given are at 0, or follow their ``<mimic>`` joint. ``chain.limits`` holds the position
limits the URDF declares.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Mapping, Optional

import numpy as np


def _rpy(r: float, p: float, y: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    x, y, z = axis
    K = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(angle) * K + (1.0 - np.cos(angle)) * (K @ K)


def pose_matrix(xyz, quat_xyzw) -> np.ndarray:
    """4x4 pose from a position and a scalar-last quaternion."""
    x, y, z, w = np.asarray(quat_xyzw, dtype=np.float64) / np.linalg.norm(quat_xyzw)
    T = np.eye(4)
    T[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    T[:3, 3] = xyz
    return T


class Chain:
    """The joint tree of a URDF file."""

    def __init__(self, urdf: str):
        root = ET.parse(urdf).getroot()
        self.joints, self.limits, self.mimic = [], {}, {}
        children = set()
        for j in root.findall("joint"):
            name, kind = j.get("name"), j.get("type")
            o = j.find("origin")
            T = np.eye(4)
            if o is not None:
                T[:3, :3] = _rpy(*[float(v) for v in o.get("rpy", "0 0 0").split()])
                T[:3, 3] = [float(v) for v in o.get("xyz", "0 0 0").split()]
            a = j.find("axis")
            axis = np.array([float(v) for v in a.get("xyz").split()]) if a is not None else np.array([1.0, 0.0, 0.0])
            n = np.linalg.norm(axis)
            self.joints.append((name, kind, j.find("parent").get("link"), j.find("child").get("link"), T, axis / n if n else axis))
            children.add(j.find("child").get("link"))
            lim, m = j.find("limit"), j.find("mimic")
            if lim is not None and kind in ("revolute", "prismatic"):
                self.limits[name] = (float(lim.get("lower", 0.0)), float(lim.get("upper", 0.0)))
            if m is not None:
                self.mimic[name] = (m.get("joint"), float(m.get("multiplier", 1.0)), float(m.get("offset", 0.0)))
        self.links = [l.get("name") for l in root.findall("link")]
        self.root = next(l for l in self.links if l not in children)
        order, done, todo = [], {self.root}, list(self.joints)      # parents before children
        while todo:
            ready = [j for j in todo if j[2] in done]
            if not ready:
                raise ValueError("the URDF joints do not form a tree")
            order += ready
            done |= {j[3] for j in ready}
            todo = [j for j in todo if j[2] not in done or j[3] not in done]
        self.joints = order

    def position(self, name: str, q: Mapping[str, float]) -> float:
        if name in q:
            return float(q[name])
        if name in self.mimic:
            src, k, off = self.mimic[name]
            return k * self.position(src, q) + off
        return 0.0

    def link_poses(self, q: Mapping[str, float], root_pose: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
        """{link: 4x4 pose} for joint positions ``q`` (rad, m). ``root_pose`` places the root link (default: identity)."""
        out = {self.root: np.eye(4) if root_pose is None else np.asarray(root_pose, dtype=np.float64)}
        for name, kind, parent, child, T, axis in self.joints:
            M = np.eye(4)
            if kind in ("revolute", "continuous"):
                M[:3, :3] = _axis_angle(axis, self.position(name, q))
            elif kind == "prismatic":
                M[:3, 3] = axis * self.position(name, q)
            elif kind != "fixed":
                raise ValueError(f"joint type {kind!r} of {name} is not supported")
            out[child] = out[parent] @ T @ M
        return out
