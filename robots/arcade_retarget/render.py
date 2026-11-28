"""Side-by-side video: a human demonstration (ARCADE-Checkout-Human) and its retargeting (FFW-SH5, two UR10e or G1).

  python -m arcade_retarget.render --release REL --retarget samples/ffw_sh5_sample/ffw_sh5 \\
      --episodes J03826_left --out preview.mp4 --webp preview.webp
  python -m arcade_retarget.render --release REL --retarget samples/ur10e_2f140_sample/ur10e_2f140 \\
      --episodes J02562_right --stride 2 --out ur10e.mp4
  python -m arcade_retarget.render --release REL --retarget samples/g1_dex3_sample/g1_dex3 \\
      --episodes J03826_left --out g1.mp4

The robot is read from PREFIX_ik.json, as in the exporter. Two UR10e: the URDF built by
``retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh``, loaded with MuJoCo's URDF importer (the UR10e collision meshes
stand in for its COLLADA visuals); the human panel shows the product as recorded in ARCADE-Checkout-Human,
the robot panel where the grippers carry it. ``--stride k`` shows every k-th step (k x speed). Unitree G1 +
Dex3-1: Unitree's MJCF (``g1_29dof_with_hand_rev_1_0.xml``, fetched by ``retarget/unitree_g1_dex3/fetch_robot.sh``), visual
meshes only, posed from the released joints and pelvis pose; the robot panel shows the product on its released path
and, because the G1 is about 1.3 m tall, zooms in on the robot (``--robot-zoom``, default 1.6).

Left: the recorded shopper (a mannequin with 21-landmark hands) and the product. Right: the
ROBOTIS FFW-SH5, the upstream MuJoCo model (``ffw_description/mujoco/ffw_sh5``, fetched by
``retarget/robotis_ffw_sh5/fetch_robot.sh``), posed from the released joint trajectories, with the
product at its retargeted pose. The model's forward kinematics match the URDF the data was
made with. Underneath: the episode's language task and when each hand holds the product; a grey
band marks where the robot blends from or to its home pose. Nothing is simulated; this is a
kinematic replay.

Requires the ``render`` extra (mujoco, pillow) and ffmpeg. Headless Linux uses MUJOCO_GL=egl.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Optional

import numpy as np

from arcade_retarget.paths import ROBOT_DIR

MJCF_REL = "ffw_description/mujoco/ffw_sh5/scene.xml"
#: canvas layout at 1920 x 1080 (scaled for other sizes): two panels over a timeline strip
LAYOUT = dict(width=1920, height=1080, strip=200, gutter=16)


class RobotScene:
    """ROBOTIS FFW-SH5 MJCF restyled to the ARCADE studio look + counter + product mocap bodies."""

    def __init__(self, counter: Dict, counter_h: float, product_meshes: Dict[str, str], robot_dir: str = ROBOT_DIR,
                 recess: Optional[Dict] = None):
        import mujoco
        from arcade_human import render as R
        self.mj, self.R = mujoco, R
        mjcf = os.path.join(robot_dir, MJCF_REL)
        if not os.path.exists(mjcf):
            raise SystemExit(f"robot model not found ({mjcf}): run bash retarget/robotis_ffw_sh5/fetch_robot.sh")
        spec = R.studio_spec(mujoco.MjSpec.from_file(mjcf))
        R.add_counter(spec, counter["x0"], counter["x1"], counter["y0"], counter["y1"], height=counter_h, recess=recess)
        self.product_body = R.add_products(spec, product_meshes)
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        m = self.model
        self.qadr = {m.joint(i).name: int(m.jnt_qposadr[i]) for i in range(m.njnt)}

    def set_robot(self, base_xyyaw, arm_names, q, head, fingers_l, fingers_r, lift: float = 0.0):
        d, a = self.data, self.qadr["floating_base"]
        x, y, yaw = base_xyyaw
        d.qpos[a:a + 3] = [x, y, 0.0]
        d.qpos[a + 3:a + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        d.qpos[self.qadr["lift_joint"]] = lift
        for n, v in zip(arm_names, q):
            d.qpos[self.qadr[str(n)]] = v
        d.qpos[self.qadr["head_joint1"]], d.qpos[self.qadr["head_joint2"]] = head
        for s, F in (("l", fingers_l), ("r", fingers_r)):
            for i in range(20):
                d.qpos[self.qadr[f"finger_{s}_joint{i + 1}"]] = F[i]

    def set_product(self, mesh_key: str, T_world: np.ndarray):
        for key, body in self.product_body.items():
            if key == mesh_key:
                self.R.set_mocap(self.model, self.data, body, T_world)
            else:
                self.R.hide_mocap(self.model, self.data, body)

    def forward(self):
        self.mj.mj_kinematics(self.model, self.data)
        self.mj.mj_camlight(self.model, self.data)     # lights/cameras follow the kinematics


class UR10eScene(RobotScene):
    """Two UR10e + Robotiq 2F-140 from the fetched URDF, in the ARCADE studio look + counter + product mocap bodies."""

    ROBOT_GROUP = 1                                    # MuJoCo puts URDF visual geometry in group 1

    def __init__(self, counter: Dict, counter_h: float, product_meshes: Dict[str, str], recess: Optional[Dict] = None):
        import mujoco
        from arcade_human import render as R
        from arcade_retarget import ur10e_2f140 as ur
        self.mj, self.R = mujoco, R
        if not os.path.exists(ur.DEFAULT_URDF):
            raise SystemExit(f"robot model not found ({ur.DEFAULT_URDF}): run bash retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh")
        spec = R.studio_spec(mujoco.MjSpec.from_string(ur.mujoco_urdf()))
        for side, b in ur.config()["bases"].items():          # pedestals under the fixed bases
            x, y, z = b["xyz"]
            spec.worldbody.add_geom(name=f"{side}_pedestal", type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[0.085, z / 2, 0],
                                    pos=[x, y, z / 2], rgba=[0.62, 0.64, 0.67, 1], group=self.ROBOT_GROUP,
                                    contype=0, conaffinity=0)
        R.add_counter(spec, counter["x0"], counter["x1"], counter["y0"], counter["y1"], height=counter_h, recess=recess)
        self.product_body = R.add_products(spec, product_meshes)
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        m = self.model
        self.qadr = {m.joint(i).name: int(m.jnt_qposadr[i]) for i in range(m.njnt)}
        self.mimic = ur.mimic_joints()
        self.ur = ur
        self.names = ur.STATE_NAMES

    def set_robot(self, state):
        """state: the 14-D dataset state (12 arm joints, then the two finger_joint values). The gripper is
        drawn at the opening the released value means (``ur10e_2f140.urdf_finger_joint``)."""
        d = self.data
        for n, v in zip(self.names, state):
            d.qpos[self.qadr[n]] = self.ur.urdf_finger_joint(v) if n.endswith("finger_joint") else v
        for j, (src, k, off) in self.mimic.items():
            if j in self.qadr:
                d.qpos[self.qadr[j]] = k * d.qpos[self.qadr[src]] + off


class G1Scene(RobotScene):
    """Unitree G1 + Dex3-1 from Unitree's MJCF (visual meshes only), in the ARCADE studio look + counter + product mocap bodies."""

    ROBOT_GROUP = 1                                    # the MJCF's visual meshes are in group 1

    def __init__(self, counter: Dict, counter_h: float, product_meshes: Dict[str, str], recess: Optional[Dict] = None,
                 stand: Optional[Dict] = None):
        import mujoco
        from arcade_human import render as R
        from arcade_retarget import g1_dex3 as g1
        self.mj, self.R = mujoco, R
        if not os.path.exists(g1.DEFAULT_MJCF):
            raise SystemExit(f"robot model not found ({g1.DEFAULT_MJCF}): run bash retarget/unitree_g1_dex3/fetch_robot.sh")
        spec = mujoco.MjSpec.from_file(g1.DEFAULT_MJCF)
        for g in list(spec.geoms):                     # drop the collision geometry (group 0); keep the floor plane
            if g.group != self.ROBOT_GROUP and g.type != mujoco.mjtGeom.mjGEOM_PLANE:
                spec.delete(g)
        spec = R.studio_spec(spec)
        R.add_counter(spec, counter["x0"], counter["x1"], counter["y0"], counter["y1"], height=counter_h, recess=recess)
        if stand and stand.get("height", 0) > 0:       # the step the robot stands on (PREFIX_ik.json "stand"), robot world
            h = float(stand["height"])
            spec.worldbody.add_geom(name="arcade_stand", type=mujoco.mjtGeom.mjGEOM_BOX, rgba=[0.42, 0.46, 0.52, 1.0],
                                    size=[(stand["x1"] - stand["x0"]) / 2, (stand["y1"] - stand["y0"]) / 2, h / 2],
                                    pos=[(stand["x0"] + stand["x1"]) / 2, (stand["y0"] + stand["y1"]) / 2, h / 2])
        self.product_body = R.add_products(spec, product_meshes)
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        m = self.model
        self.qadr = {m.joint(i).name: int(m.jnt_qposadr[i]) for i in range(m.njnt)}
        self.base = self.qadr[next(m.joint(i).name for i in range(m.njnt) if m.jnt_type[i] == mujoco.mjtJoint.mjJNT_FREE)]
        self.names = g1.JOINT_NAMES

    #: robot panel zoom (camera distance divided by this); the G1 is about 1.3 m tall, so the shared view shows it small.
    #: The view keeps the feet and the step the robot stands on in the picture
    ZOOM = 1.15

    @staticmethod
    def robot_view(state: np.ndarray, counter_h: float, zoom: float):
        """Camera of the robot panel for an episode: the standard ARCADE direction, centred on the robot's chest
        in front of the pelvis, ``zoom`` times closer than the shared view."""
        from arcade_human import render as R
        x, y = np.median(state[:, 43]), np.median(state[:, 44])
        return R.View(lookat=(float(x) + 0.12, float(y), float(np.median(state[:, 45])) - 0.05), distance=2.65 / zoom, azimuth=160.0,
                      elevation=-18.0)

    def set_robot(self, state):
        """state: the 50-D dataset state (43 joints, then the pelvis pose [x y z qx qy qz qw] in the robot world)."""
        d = self.data
        for n, v in zip(self.names, state[:43]):
            d.qpos[self.qadr[n]] = v
        x, y, z, qx, qy, qz, qw = state[43:50]
        d.qpos[self.base:self.base + 7] = [x, y, z, qw, qx, qy, qz]


def _render_ur10e(ds, retarget: str, episodes: List[str], out: str, webp: Optional[str], width: int, height: int,
                  webp_width: int, stride: int) -> str:
    from arcade_retarget import ur10e_2f140 as ur
    ik = np.load(retarget + "_ik.npz")
    return _render_holding_robot(ds, retarget, episodes, out, webp, width, height, webp_width, stride, UR10eScene,
                                 lambda e: np.concatenate([ik[e + "|q"], ik[e + "|gripper"]], 1), ur.task_sentence,
                                 "2 × UR10e + Robotiq 2F-140 · retargeted")


def _render_g1(ds, retarget: str, episodes: List[str], out: str, webp: Optional[str], width: int, height: int,
               webp_width: int, stride: int, zoom: Optional[float] = None) -> str:
    from arcade_retarget import g1_dex3 as g1
    ik = np.load(retarget + "_ik.npz")
    ch = float(json.load(open(retarget + "_ik.json")).get("counter_h", 0.8))

    def state(e):
        pelvis = ik[e + "|pelvis"].astype(np.float64).copy()
        pelvis[:, 2] += ch                                            # counter frame -> robot world
        return np.concatenate([ik[e + "|q"], pelvis], 1)
    z = G1Scene.ZOOM if zoom is None else zoom
    return _render_holding_robot(ds, retarget, episodes, out, webp, width, height, webp_width, stride, G1Scene, state,
                                 g1.task_sentence, "Unitree G1 + Dex3-1 · retargeted",
                                 robot_view=(lambda st: G1Scene.robot_view(st, ch, z)) if z > 1 else None)


def _render_holding_robot(ds, retarget: str, episodes: List[str], out: str, webp: Optional[str], width: int, height: int,
                          webp_width: int, stride: int, scene_cls, state_of, task_sentence, label: str,
                          robot_view=None) -> str:
    """Human panel | robot panel for robots whose raw outputs record when each gripper / hand holds the product
    (``obj_holding``): two UR10e, G1. ``robot_view(state)`` gives the robot panel its own camera per episode
    (default: the human panel's)."""
    import mujoco
    from PIL import Image
    from arcade_human import render as R
    from arcade_human.style import chip, strip

    ik, ob = np.load(retarget + "_ik.npz"), np.load(retarget + "_obj.npz")
    ikm = json.load(open(retarget + "_ik.json"))
    obm = json.load(open(retarget + "_obj.json"))["episodes"]
    ch = float(ikm.get("counter_h", 0.8))
    fps = float(ikm.get("args", {}).get("fps", 19.94))
    eps = {e: ds.load(e) for e in episodes}
    meshes = {obm[e]["mesh"]: os.path.join(ds.root, obm[e]["mesh"]) for e in episodes}
    meshes.update({"human:" + e: eps[e].product_mesh_path for e in episodes})
    sc = scene_cls(ikm["counter"], ch, meshes, recess=dict(R.CAPTURE_RECESS, y=R.shopper_y(ds, episodes)))
    if ikm.get("stand"):                                # the G1 stands on a step in front of the counter
        sc = scene_cls(ikm["counter"], ch, meshes, recess=dict(R.CAPTURE_RECESS, y=R.shopper_y(ds, episodes)), stand=ikm["stand"])
    s = width / LAYOUT["width"]
    strip_h = int(round(LAYOUT["strip"] * height / LAYOUT["height"] / 2)) * 2
    gutter = max(2, int(round(LAYOUT["gutter"] * s / 2)) * 2)
    pw, ph = (width - gutter) // 2, height - strip_h
    r = mujoco.Renderer(sc.model, ph * R.SUPERSAMPLE, pw * R.SUPERSAMPLE, max_geom=6000)
    cam = R.make_camera(R.default_view(ikm["counter"], height=ch))
    opt_h, opt_r = mujoco.MjvOption(), mujoco.MjvOption()
    opt_h.geomgroup[scene_cls.ROBOT_GROUP] = 0          # human panel: hide the robot
    enc = R.ffmpeg_writer(out, width, height, fps)
    off = np.array([0.0, 0.0, ch])
    try:
        for e in episodes:
            ep = eps[e]
            f0 = int(ep.frame_index[0])
            frames = ik[e + "|frames"].astype(int)
            n = len(frames)
            hold = ob[e + "|obj_holding"]
            holding = {"left": hold[:, 0], "right": hold[:, 1]}
            events = [dict(frame=int(min(np.searchsorted(frames, x["session_frame"]), n - 1)), hand=x["hand"],
                           kind=x["kind"]) for x in ep.events]
            task = task_sentence(obm[e]["dims"]["shape"], obm[e]["holding"])
            Th = ep.object_matrix().astype(np.float64)
            state = state_of(e)
            cam_r = R.make_camera(robot_view(state)) if robot_view else cam
            for t in range(0, n, stride):
                k = int(np.clip(frames[t] - f0, 0, len(ep) - 1))
                sc.set_robot(state[t])
                if np.all(np.isfinite(Th[k])):
                    T = Th[k].copy()
                    T[:3, 3] += off
                    sc.set_product("human:" + e, T)
                else:
                    sc.set_product(None, None)
                sc.forward()
                r.update_scene(sc.data, camera=cam, scene_option=opt_h)
                R.draw_shopper(r.scene, ep.body_position[k].astype(np.float64) + off,
                               {side: ep.hand_position(side)[k].astype(np.float64) + off for side in ("left", "right")})
                img_h = Image.fromarray(R.render_rgb(r, pw, ph))
                chip(img_h, (int(24 * s), int(24 * s)), "Human demonstration", size=int(26 * s))
                T = ob[e + "|obj_T"][t].astype(np.float64).copy()
                T[2, 3] += ch
                sc.set_product(obm[e]["mesh"], T)
                sc.forward()
                r.update_scene(sc.data, camera=cam_r, scene_option=opt_r)
                img_r = Image.fromarray(R.render_rgb(r, pw, ph))
                chip(img_r, (int(24 * s), int(24 * s)), label, size=int(26 * s))
                chip(img_r, (int(24 * s), ph - int(74 * s)), "kinematic replay" + (f" · {stride}× speed" if stride > 1 else ""),
                     size=int(24 * s), bold=False, alpha=200)
                canvas = Image.new("RGB", (width, height), (246, 247, 249))
                canvas.paste(img_h, (0, 0))
                canvas.paste(img_r, (width - pw, 0))
                canvas.paste(strip(width, strip_h, n, t, holding, events, fps, task), (0, ph))
                enc.stdin.write(np.asarray(canvas).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
        r.close()
    if webp:
        R.mp4_to_webp(out, webp, width=min(width, webp_width))
    return out


def render(release: str, retarget: str, episodes: List[str], out: str, webp: Optional[str] = None,
           width: int = 1920, height: int = 1080, webp_width: int = 1280, stride: int = 1,
           robot_zoom: Optional[float] = None) -> str:
    """Human panel | robot panel over the task/holding strip; MP4 (+ optional animated WebP)."""
    try:
        import mujoco
    except ImportError:
        raise SystemExit('rendering needs the render extra: pip install -e ".[render]"')
    from PIL import Image
    from arcade_human import ArcadeHuman
    from arcade_human import render as R
    from arcade_human.style import chip, strip
    from arcade_retarget.export_lerobot import task_of

    ds = ArcadeHuman(release)
    ik = np.load(retarget + "_ik.npz")
    have = {k.split("|")[0] for k in ik.files if k.endswith("|frames")} & set(ds.episode_ids)
    unknown = [e for e in episodes if e not in have]
    if unknown:
        raise SystemExit(f"unknown episodes {unknown}: both {release} and {retarget}_ik.npz must contain them "
                         f"(available: {', '.join(sorted(have)[:6])}{', ...' if len(have) > 6 else ''})")
    robot = json.load(open(retarget + "_ik.json")).get("robot")
    if robot == "ur10e_2f140":
        return _render_ur10e(ds, retarget, episodes, out, webp, width, height, webp_width, stride)
    if robot == "g1_dex3":
        return _render_g1(ds, retarget, episodes, out, webp, width, height, webp_width, stride, robot_zoom)
    hd = np.load(retarget + "_hand.npz")
    ob = np.load(retarget + "_obj.npz")
    ikm = json.load(open(retarget + "_ik.json"))
    obm = json.load(open(retarget + "_obj.json"))["episodes"]
    ch = float(ikm.get("counter_h", 0.8))
    fps = float(ikm.get("args", {}).get("fps", 19.94))
    meshes = {obm[e]["mesh"]: os.path.join(ds.root, obm[e]["mesh"]) for e in episodes}
    sc = RobotScene(ikm["counter"], ch, meshes, recess=dict(R.CAPTURE_RECESS, y=R.shopper_y(ds, episodes)))
    s = width / LAYOUT["width"]
    strip_h = int(round(LAYOUT["strip"] * height / LAYOUT["height"] / 2)) * 2
    gutter = max(2, int(round(LAYOUT["gutter"] * s / 2)) * 2)
    pw, ph = (width - gutter) // 2, height - strip_h
    r = mujoco.Renderer(sc.model, ph * R.SUPERSAMPLE, pw * R.SUPERSAMPLE, max_geom=6000)
    cam = R.make_camera(R.default_view(ikm["counter"], height=ch))
    opt_h, opt_r = mujoco.MjvOption(), mujoco.MjvOption()
    opt_h.geomgroup[2] = 0                      # human panel: hide the robot's visual geoms
    enc = R.ffmpeg_writer(out, width, height, fps)
    try:
        for e in episodes:
            ep = ds.load(e)
            f0 = int(ep.frame_index[0])
            frames = ik[e + "|frames"].astype(int)
            n = len(frames)
            holding = {side: np.zeros(n, bool) for side in ("left", "right")}
            for h in obm[e]["holding"]:
                holding[h["hand"]][h["start"]:h["end"]] = True
            events = [dict(frame=int(min(np.searchsorted(frames, x["session_frame"]), n - 1)), hand=x["hand"],
                           kind=x["kind"]) for x in ep.events]
            task = task_of(obm[e])
            blend = ik[e + "|w"] < 0.999 if e + "|w" in ik.files else None     # robot blends from/to its home pose
            off = np.array([0.0, 0.0, ch])
            for t in range(n):
                k = int(np.clip(frames[t] - f0, 0, len(ep) - 1))
                T = ob[e + "|obj_T"][t].astype(np.float64).copy()
                T[2, 3] += ch
                sc.set_product(obm[e]["mesh"], T)
                b = ik[e + "|base_traj"][t]
                sc.set_robot((b[0], b[1], b[2]), ik[e + "|joint_names"], ik[e + "|q"][t], ik[e + "|head"][t],
                             hd[e + "|left__fingers"][t], hd[e + "|right__fingers"][t])
                sc.forward()
                r.update_scene(sc.data, camera=cam, scene_option=opt_h)
                R.draw_shopper(r.scene, ep.body_position[k].astype(np.float64) + off,
                               {side: ep.hand_position(side)[k].astype(np.float64) + off for side in ("left", "right")})
                img_h = Image.fromarray(R.render_rgb(r, pw, ph))
                chip(img_h, (int(24 * s), int(24 * s)), "Human demonstration", size=int(26 * s))
                r.update_scene(sc.data, camera=cam, scene_option=opt_r)
                img_r = Image.fromarray(R.render_rgb(r, pw, ph))
                chip(img_r, (int(24 * s), int(24 * s)), "ROBOTIS FFW-SH5 · retargeted", size=int(26 * s))
                chip(img_r, (int(24 * s), ph - int(74 * s)), "kinematic replay", size=int(24 * s), bold=False, alpha=200)
                canvas = Image.new("RGB", (width, height), (246, 247, 249))
                canvas.paste(img_h, (0, 0))
                canvas.paste(img_r, (width - pw, 0))
                canvas.paste(strip(width, strip_h, n, t, holding, events, fps, task, shade=blend,
                                   shade_label="robot blends from / to its home pose"), (0, ph))
                enc.stdin.write(np.asarray(canvas).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
        r.close()
    if webp:
        R.mp4_to_webp(out, webp, width=min(width, webp_width))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="ARCADE-Checkout-Human release root")
    ap.add_argument("--retarget", required=True, help="retargeting output prefix")
    ap.add_argument("--episodes", required=True, help="comma-separated episode ids, rendered one after another")
    ap.add_argument("--out", required=True, help="output .mp4")
    ap.add_argument("--webp", default=None, help="also write an animated WebP (for READMEs)")
    ap.add_argument("--width", type=int, default=1920, help="video width")
    ap.add_argument("--height", type=int, default=1080, help="video height")
    ap.add_argument("--webp-width", type=int, default=1280)
    ap.add_argument("--stride", type=int, default=1, help="show every k-th output step (UR10e, G1; k x speed)")
    ap.add_argument("--robot-zoom", type=float, default=None,
                    help="G1: zoom of the robot panel's camera on the robot (default 1.6; 1 or less: the human panel's view)")
    a = ap.parse_args()
    import sys
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("MUJOCO_GL", "egl")          # headless Linux; macOS/Windows use the default
    print(render(a.release, a.retarget, [e for e in a.episodes.split(",") if e], a.out, a.webp, a.width, a.height,
                 a.webp_width, a.stride, a.robot_zoom))


if __name__ == "__main__":
    main()
