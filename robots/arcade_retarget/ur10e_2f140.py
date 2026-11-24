"""Two UR10e arms with Robotiq 2F-140 grippers: names, layout, gripper table and the robot description.

The arms and grippers come from their upstream descriptions (fetched by ``retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh``):

* UR10e: Universal Robots ``Universal_Robots_ROS2_Description`` (BSD-3-Clause);
* 2F-140: ROS-Industrial ``robotiq`` (``robotiq_2f_140_gripper_visualization``, BSD-2-Clause).

``python -m arcade_retarget.ur10e_2f140 urdf`` expands both xacro files and joins two arms, two grippers and the
pedestal placement of ``configs/ur10e_2f140.json`` into one URDF whose joint names are the dataset's state names
(``left_shoulder_pan_joint`` ... ``right_finger_joint``). Needs the ``xacro`` package (``pip install xacro``).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Sequence

import numpy as np

from .paths import CONFIG_DIR, REPO_ROOT

ROBOT = "ur10e_2f140"
ROBOT_TYPE = "ur10e_2f140_dual"
SIDES = ("left", "right")
ARM_JOINTS = ["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"]
JOINT_NAMES = [f"{s}_{j}" for s in SIDES for j in ARM_JOINTS]            # the 12 arm joints, left arm first
GRIPPER_NAMES = [f"{s}_finger_joint" for s in SIDES]                     # Robotiq 2F-140 finger_joint, rad
STATE_NAMES = JOINT_NAMES + GRIPPER_NAMES

#: where fetch_robot.sh puts the upstream descriptions (override with ARCADE_UR10E_DIR)
ROBOT_DIR = os.environ.get("ARCADE_UR10E_DIR", os.path.join(REPO_ROOT, "retarget", "universal_robots_ur10e_robotiq_2f140"))
UPSTREAM_DIR = os.path.join(ROBOT_DIR, "upstream")
DEFAULT_URDF = os.path.join(ROBOT_DIR, "ur10e_2f140_dual.urdf")
UR_PACKAGE = "ur_description"
ROBOTIQ_PACKAGE = "robotiq_2f_140_gripper_visualization"


def package_dirs(upstream: str = UPSTREAM_DIR) -> List[str]:
    """Roots that resolve the ``package://`` mesh paths of the URDF (pinocchio ``package_dirs``)."""
    return [upstream, os.path.join(upstream, "robotiq")]


def config(path: Optional[str] = None) -> Dict:
    """Layout, mount, rest pose and gripper table (``configs/ur10e_2f140.json``)."""
    return json.load(open(path or os.path.join(CONFIG_DIR, "ur10e_2f140.json")))


def gripper_gap(finger_joint, cfg: Optional[Dict] = None) -> np.ndarray:
    """Inner-pad gap (m) of the simulated 2F-140 used for the retargeting at a finger_joint value (rad)."""
    g = (cfg or config())["gripper"]
    return np.interp(finger_joint, g["finger_joint"], g["pad_gap_m"])


# --- tasks ---------------------------------------------------------------------------------------------

OBJECT_WORD = {"cylinder": "bottle", "box": "box"}


def holding_runs(holding: np.ndarray) -> List[Dict]:
    """Intervals [start, end) in output steps where each gripper is closed on the product.

    holding: (n, 2) bool, left then right."""
    out = []
    for c, side in enumerate(SIDES):
        h = np.asarray(holding[:, c], bool)
        edges = np.flatnonzero(np.diff(np.r_[0, h.astype(np.int8), 0]))
        out += [dict(arm=side, start=int(a), end=int(b)) for a, b in zip(edges[::2], edges[1::2])]
    return sorted(out, key=lambda r: (r["start"], r["end"]))


def task_kind(runs: Sequence[Dict]) -> str:
    """one_arm, pass (ends in the other gripper) or both_arms (both hold it, the first one puts it down)."""
    if len({r["arm"] for r in runs}) < 2:
        return "one_arm"
    first = min(runs, key=lambda r: r["start"])["arm"]
    last = max(runs, key=lambda r: (r["end"], r["start"]))["arm"]
    return "pass" if first != last else "both_arms"


def task_sentence(shape: str, runs: Sequence[Dict]) -> str:
    """Language task of an episode from the robot's own holding intervals."""
    obj = OBJECT_WORD.get(shape, "product")
    where = " from the checkout counter"
    if not runs:
        return f"Pick up the {obj}{where} and put it down."
    first = min(runs, key=lambda r: r["start"])["arm"]
    last = max(runs, key=lambda r: (r["end"], r["start"]))["arm"]
    kind = task_kind(runs)
    if kind == "one_arm":
        return f"Pick up the {obj}{where} with the {first} arm and put it down."
    if kind == "pass":
        return f"Pick up the {obj}{where} with the {first} arm, pass it to the {last} arm, and put it down."
    return f"Pick up the {obj}{where} with the {first} arm, hold it with both arms, and put it down with the {first} arm."


# --- robot description -----------------------------------------------------------------------------------

def _xacro(path: str, package: str, package_root: str, args: Dict[str, str]) -> ET.Element:
    """Expand one upstream xacro file. ``$(find <package>)`` is resolved without a ROS installation by
    expanding a copy whose ``$(find ...)`` points to the fetched package."""
    import xacro
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, package)
        shutil.copytree(package_root, dst, ignore=shutil.ignore_patterns(".git", "meshes"))
        for root, _, files in os.walk(dst):
            for f in files:
                if f.endswith(".xacro"):
                    p = os.path.join(root, f)
                    s = open(p).read().replace(f"$(find {package})", dst)
                    open(p, "w").write(s)
        rel = os.path.relpath(path, package_root)
        doc = xacro.process_file(os.path.join(dst, rel), mappings=args)
        return ET.fromstring(doc.toxml())


def _prefixed(root: ET.Element, prefix: str, drop_links=(), drop_joints=()) -> List[ET.Element]:
    """Links and joints of a URDF with every link and joint name prefixed; control and simulator tags dropped."""
    out = []
    for el in root:
        if el.tag == "link" and el.get("name") not in drop_links:
            el = copy.deepcopy(el)
            el.set("name", prefix + el.get("name"))
            out.append(el)
        elif el.tag == "joint" and el.get("name") not in drop_joints:
            el = copy.deepcopy(el)
            el.set("name", prefix + el.get("name"))
            for tag in ("parent", "child"):
                el.find(tag).set("link", prefix + el.find(tag).get("link"))
            m = el.find("mimic")
            if m is not None:
                m.set("joint", prefix + m.get("joint"))
            out.append(el)
    return out


def _fixed(name: str, parent: str, child: str, xyz: Sequence[float], rpy: Sequence[float]) -> ET.Element:
    j = ET.Element("joint", name=name, type="fixed")
    ET.SubElement(j, "origin", xyz=" ".join(repr(float(v)) for v in xyz), rpy=" ".join(repr(float(v)) for v in rpy))
    ET.SubElement(j, "parent", link=parent)
    ET.SubElement(j, "child", link=child)
    return j


def build_urdf(upstream: str = UPSTREAM_DIR, out: str = DEFAULT_URDF, cfg: Optional[Dict] = None) -> str:
    """Write the two-arm URDF (robot world frame: floor z = 0) and return its path."""
    cfg = cfg or config()
    ur_root = os.path.join(upstream, UR_PACKAGE)
    rq_root = os.path.join(upstream, "robotiq", ROBOTIQ_PACKAGE)
    ur = _xacro(os.path.join(ur_root, "urdf", "ur.urdf.xacro"), UR_PACKAGE, ur_root, {"ur_type": "ur10e", "name": "ur"})
    rq = _xacro(os.path.join(rq_root, "urdf", "robotiq_arg2f_140_model.xacro"), ROBOTIQ_PACKAGE, rq_root, {})
    robot = ET.Element("robot", name=ROBOT_TYPE)
    robot.append(ET.Comment(" generated by arcade_retarget.ur10e_2f140 from the upstream UR10e and Robotiq 2F-140 descriptions "))
    ET.SubElement(robot, "link", name="world")
    m = cfg["mount"]
    for s in SIDES:
        p = s + "_"
        b = cfg["bases"][s]
        robot.append(_fixed(f"{p}base_mount", "world", p + "base_link", b["xyz"], b["rpy"]))
        for el in _prefixed(ur, p, drop_links=("world",), drop_joints=("base_joint",)):
            robot.append(el)
        robot.append(_fixed(f"{p}gripper_mount", p + m["parent"], p + m["child"], m["xyz"], m["rpy"]))
        for el in _prefixed(rq, p):
            robot.append(el)
    ET.indent(robot)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    s = ET.tostring(robot, encoding="unicode")
    s = re.sub(r'<material name="" />', "", s)
    open(out, "w").write('<?xml version="1.0"?>\n' + s + "\n")
    return out


ARM_RGBA = "0.80 0.82 0.85 1"
GRIPPER_RGBA = "0.22 0.23 0.25 1"


def mimic_joints(urdf: str = DEFAULT_URDF) -> Dict[str, tuple]:
    """{joint: (driving joint, multiplier, offset)} from the URDF's <mimic> tags."""
    out = {}
    for j in ET.parse(urdf).getroot().findall("joint"):
        m = j.find("mimic")
        if m is not None:
            out[j.get("name")] = (m.get("joint"), float(m.get("multiplier", 1.0)), float(m.get("offset", 0.0)))
    return out


def mujoco_urdf(urdf: str = DEFAULT_URDF, upstream: str = UPSTREAM_DIR) -> str:
    """The two-arm URDF prepared for MuJoCo's URDF importer (preview rendering): visual geometry only, absolute
    mesh paths, and the UR10e collision STLs in place of its COLLADA visuals (MuJoCo does not read .dae)."""
    root = ET.parse(urdf).getroot()
    roots = {UR_PACKAGE: os.path.join(upstream, UR_PACKAGE), ROBOTIQ_PACKAGE: os.path.join(upstream, "robotiq", ROBOTIQ_PACKAGE)}
    for link in root.findall("link"):
        for c in link.findall("collision"):
            link.remove(c)
        gripper = any(k in link.get("name") for k in ("robotiq", "knuckle", "finger"))
        for v in link.findall("visual"):
            mesh = v.find("geometry/mesh")
            if mesh is None:
                continue
            pkg, rel = re.match(r"package://([^/]+)/(.*)", mesh.get("filename")).groups()
            if pkg == UR_PACKAGE:
                rel = rel.replace("/visual/", "/collision/").replace(".dae", ".stl")
            mesh.set("filename", os.path.join(roots[pkg], rel))
            for mat in v.findall("material"):
                v.remove(mat)
            mat = ET.SubElement(v, "material", name="arcade_gripper" if gripper else "arcade_arm")
            ET.SubElement(mat, "color", rgba=GRIPPER_RGBA if gripper else ARM_RGBA)
    mj = ET.SubElement(root, "mujoco")
    ET.SubElement(mj, "compiler", strippath="false", fusestatic="false", discardvisual="false", balanceinertia="true")
    return ET.tostring(root, encoding="unicode")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("urdf", help="write the two-arm URDF from the fetched upstream descriptions")
    u.add_argument("--upstream", default=UPSTREAM_DIR)
    u.add_argument("--out", default=DEFAULT_URDF)
    a = ap.parse_args()
    if a.cmd == "urdf":
        print(build_urdf(a.upstream, a.out))


if __name__ == "__main__":
    main()
