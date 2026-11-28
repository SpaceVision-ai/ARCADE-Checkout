"""Studio renders of ARCADE-Checkout-Human episodes (MuJoCo, headless).

    arcade-human video    RELEASE J03826_left out.mp4 --webp out.webp   # scene + hands close-up + timeline
    arcade-human still    RELEASE J03826_left out.png --frame 80
    arcade-human grid     RELEASE J03826_left,J02562_right,... out.mp4 --webp out.webp
    arcade-human products RELEASE products.png

Everything is drawn from the released files: the counter, the episode's textured product mesh
at its 6-DoF pose, and the shopper as a light mannequin (upper body from the 23 body joints)
with blue (left) and orange (right) 21-landmark hands. Videos carry a timeline strip with the
episode's task, when each hand holds the product, and grasp/release markers.

The look follows the MuJoCo Menagerie renders: light studio backdrop, tiled floor, key/fill/rim
lights with soft shadows, 8x MSAA, frames rendered at 2x and downsampled.

Requires the ``render`` extra (mujoco, pillow) and ffmpeg for videos. Headless Linux: MUJOCO_GL=egl
(or osmesa).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .reader import ArcadeHuman, Episode
from .style import PALETTE, SIDES, chip, hex_rgb, strip

COUNTER_HEIGHT = 0.80          # display height of the counter top above the floor (m)
SUPERSAMPLE = 2                # render at 2x and downsample (crisp edges)
#: counter-top footprint of the capture counter in the counter frame (m), covering every resting product
#: pose of the full release. Renders of any subset (such as the in-repo sample) use it, so they match.
CAPTURE_COUNTER = dict(x0=-0.551, x1=0.057, y0=-0.840, y1=0.541)
#: the footprint is inferred (a box around the resting products), so it overlaps where the shopper
#: stands; renders cut this recess into the counter in front of the shopper. No product rests in it.
CAPTURE_RECESS = dict(x=-0.38, half_width=0.20)
HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (0, 9), (9, 10), (10, 11),
              (11, 12), (0, 13), (13, 14), (14, 15), (15, 16), (0, 17), (17, 18), (18, 19), (19, 20),
              (5, 9), (9, 13), (13, 17)]
#: canvas layout of the hero video at 1920 x 1080 (scaled for other sizes)
HERO = dict(width=1920, height=1080, strip=200, scene=1248, gutter=16)


def texture_of(obj_path: str) -> Optional[str]:
    """Texture image referenced by an OBJ's MTL (map_Kd), if any."""
    d = os.path.dirname(obj_path)
    for line in open(obj_path, errors="replace"):
        if line.startswith("mtllib"):
            mtl = os.path.join(d, line.split(None, 1)[1].strip())
            if os.path.exists(mtl):
                for m in open(mtl, errors="replace"):
                    if m.strip().startswith("map_Kd"):
                        p = os.path.join(d, m.strip().split(None, 1)[1].strip())
                        return p if os.path.exists(p) else None
            break
    p = os.path.join(d, "material_0.png")
    return p if os.path.exists(p) else None


# --------------------------------------------------------------------------- scene
def studio_spec(spec=None):
    """A MuJoCo spec with the ARCADE studio look; pass an existing spec (e.g. a robot scene) to restyle it.

    Light gradient sky, tiled light floor, one shadow-casting key light plus fill and rim lights,
    8x MSAA, 8192 shadow map, narrow field of view.
    NOTE: call mj_camlight (or mj_forward) after mj_kinematics, otherwise model lights stay dark.
    """
    import mujoco
    if spec is None:
        spec = mujoco.MjSpec()
    sky = next((t for t in spec.textures if t.type == mujoco.mjtTexture.mjTEXTURE_SKYBOX), None)
    if sky is None:
        sky = spec.add_texture(name="arcade_sky", type=mujoco.mjtTexture.mjTEXTURE_SKYBOX,
                               builtin=mujoco.mjtBuiltin.mjBUILTIN_GRADIENT, width=512, height=3072)
    sky.rgb1, sky.rgb2 = [0.97, 0.97, 0.98], [0.84, 0.85, 0.87]
    tex = next((t for t in spec.textures if t.name == "groundplane"), None)
    if tex is None:
        tex = spec.add_texture(name="groundplane", type=mujoco.mjtTexture.mjTEXTURE_2D,
                               builtin=mujoco.mjtBuiltin.mjBUILTIN_CHECKER, mark=mujoco.mjtMark.mjMARK_EDGE,
                               width=128, height=128)
    tex.rgb1 = tex.rgb2 = [0.90, 0.905, 0.915]
    tex.markrgb = [0.80, 0.81, 0.83]
    mat = next((m for m in spec.materials if m.name == "groundplane"), None)
    if mat is None:
        mat = spec.add_material(name="groundplane")
        mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = "groundplane"
        spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05],
                                material="groundplane", contype=0, conaffinity=0)
    mat.texuniform, mat.texrepeat, mat.reflectance, mat.specular, mat.shininess = True, [2, 2], 0.0, 0.0, 0.0
    spec.stat.center, spec.stat.extent = [-0.25, 0.0, 0.9], 1.0      # also sizes the shadow map (x shadowclip)
    v = spec.visual
    v.global_.offwidth, v.global_.offheight, v.global_.fovy = 3840, 2400, 30
    v.quality.shadowsize, v.quality.offsamples = 8192, 8
    v.headlight.ambient, v.headlight.diffuse, v.headlight.specular = [0.32] * 3, [0.22] * 3, [0.04] * 3
    v.map.znear, v.map.zfar, v.map.haze, v.map.shadowclip = 0.01, 40, 0.45, 2.5
    v.rgba.haze = [0.84, 0.85, 0.87, 1.0]
    for light in list(spec.lights):
        spec.delete(light)
    wb, D = spec.worldbody, mujoco.mjtLightType.mjLIGHT_DIRECTIONAL
    wb.add_light(name="arcade_key", type=D, pos=[1.0, 1.1, 3.6], dir=[-0.45, -0.37, -0.81],
                 diffuse=[0.50, 0.49, 0.47], specular=[0.2] * 3, castshadow=True)
    wb.add_light(name="arcade_fill", type=D, pos=[0.6, -2.4, 2.6], dir=[-0.25, 0.80, -0.55],
                 diffuse=[0.18, 0.19, 0.21], specular=[0.0] * 3, castshadow=False)
    wb.add_light(name="arcade_rim", type=D, pos=[-2.4, 0.0, 2.6], dir=[0.75, 0.0, -0.65],
                 diffuse=[0.16] * 3, specular=[0.15] * 3, castshadow=False)
    return spec


def _minus_recess(x0, x1, y0, y1, recess=None, grow=0.0):
    """Rectangles covering [x0, x1] x [y0, y1] minus the recess [x0, x] x [y - half_width, y + half_width]
    (grown by `grow`)."""
    if not recess or recess["x"] <= x0 or "y" not in recess:
        return [(x0, x1, y0, y1)]
    rx = recess["x"] + grow
    ry0, ry1 = recess["y"] - recess["half_width"] - grow, recess["y"] + recess["half_width"] + grow
    out = [(rx, x1, y0, y1)]
    if ry0 > y0:
        out.append((x0, rx, y0, ry0))
    if ry1 < y1:
        out.append((x0, rx, ry1, y1))
    return out


def add_counter(spec, x0: float, x1: float, y0: float, y1: float, height: float = COUNTER_HEIGHT,
                recess: Optional[Dict[str, float]] = None):
    """Counter: a 4 cm top at `height` (floor at 0) over a set-back body, optionally with a recess cut
    into the near edge, where the shopper stands."""
    import mujoco
    top = spec.add_material(name="arcade_counter_top", rgba=hex_rgb(PALETTE["counter_top"]) + [1.0],
                            specular=0.15, shininess=0.25)
    body = spec.add_material(name="arcade_counter_body", rgba=hex_rgb(PALETTE["counter_body"]) + [1.0],
                             specular=0.05, shininess=0.1)
    b = spec.worldbody.add_body(name="arcade_counter")
    BOX = mujoco.mjtGeom.mjGEOM_BOX
    if height > 0.06:
        inset = 0.06
        for a0, a1, b0, b1 in _minus_recess(x0 + inset, x1 - inset, y0 + inset, y1 - inset, recess, grow=inset):
            if a1 - a0 > 0.01 and b1 - b0 > 0.01:
                b.add_geom(type=BOX, size=[(a1 - a0) / 2, (b1 - b0) / 2, (height - 0.04) / 2],
                           pos=[(a0 + a1) / 2, (b0 + b1) / 2, (height - 0.04) / 2], material=body.name,
                           contype=0, conaffinity=0)
    for a0, a1, b0, b1 in _minus_recess(x0, x1, y0, y1, recess):
        b.add_geom(type=BOX, size=[(a1 - a0) / 2, (b1 - b0) / 2, 0.02], pos=[(a0 + a1) / 2, (b0 + b1) / 2, height - 0.02],
                   material=top.name, contype=0, conaffinity=0)


def add_products(spec, meshes: Dict[str, str]) -> Dict[str, str]:
    """One mocap body per product mesh (textured if the MTL names a texture). Returns key -> body name."""
    import mujoco
    bodies = {}
    for k, (key, obj) in enumerate(sorted(meshes.items())):
        tex = texture_of(obj)
        spec.add_mesh(name=f"arcade_mesh_{k}", file=os.path.abspath(obj))
        b = spec.worldbody.add_body(name=f"arcade_product_{k}", mocap=True, pos=[0, 0, -10])
        g = b.add_geom(type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"arcade_mesh_{k}", contype=0, conaffinity=0, group=0)
        if tex:
            t = spec.add_texture(name=f"arcade_tex_{k}", type=mujoco.mjtTexture.mjTEXTURE_2D, file=os.path.abspath(tex))
            mat = spec.add_material(name=f"arcade_mat_{k}", specular=0.35, shininess=0.5)
            mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = t.name
            g.material = mat.name
        else:
            g.rgba = [0.35, 0.65, 0.4, 1.0]
        bodies[key] = b.name
    return bodies


def set_mocap(model, data, body: str, T: np.ndarray):
    from .geometry import matrix_to_quat_xyzw
    mid = int(model.body_mocapid[model.body(body).id])
    data.mocap_pos[mid] = T[:3, 3]
    x, y, z, w = matrix_to_quat_xyzw(T[:3, :3])
    data.mocap_quat[mid] = [w, x, y, z]


def hide_mocap(model, data, body: str):
    data.mocap_pos[int(model.body_mocapid[model.body(body).id])] = [0, 0, -10]


# --------------------------------------------------------------------------- shopper
def _add(scn, kind, size, pos, rgba, p2=None, r=None, specular=0.15, shininess=0.3):
    """Append one geom to an mjvScene (skipped if any point is not finite or the scene is full)."""
    import mujoco
    if scn.ngeom >= scn.maxgeom or not np.all(np.isfinite(pos)) or (p2 is not None and not np.all(np.isfinite(p2))):
        return
    g = scn.geoms[scn.ngeom]
    mujoco.mjv_initGeom(g, kind, np.asarray(size, np.float64), np.asarray(pos, np.float64), np.eye(3).ravel(),
                        np.asarray(rgba, np.float32))
    if p2 is not None:
        mujoco.mjv_connector(g, kind, r, np.asarray(pos, np.float64), np.asarray(p2, np.float64))
    g.specular, g.shininess = specular, shininess
    scn.ngeom += 1


def draw_hands(scn, hands: Dict[str, np.ndarray]):
    """21-landmark hand skeletons: blue left, orange right. Points are in the world frame."""
    import mujoco
    CAP, SPH = mujoco.mjtGeom.mjGEOM_CAPSULE, mujoco.mjtGeom.mjGEOM_SPHERE
    for side, h in hands.items():
        c = hex_rgb(PALETTE[side]) + [1.0]
        for i, j in HAND_EDGES:
            _add(scn, CAP, [0, 0, 0], h[i], c, p2=h[j], r=0.0075, specular=0.35, shininess=0.6)
        for i in range(21):
            _add(scn, SPH, [0.0094] * 3, h[i], c, specular=0.35, shininess=0.6)


def draw_shopper(scn, body: np.ndarray, hands: Dict[str, np.ndarray], color: Optional[str] = None):
    """Append the shopper to an mjvScene: a light mannequin built from the upper-body joints (torso,
    shoulders, neck, head, arms) and the two coloured hand skeletons. Points are in the world frame.
    The lower body is not drawn: it is hidden by the counter and not reliable in the data."""
    import mujoco
    CAP, ELL = mujoco.mjtGeom.mjGEOM_CAPSULE, mujoco.mjtGeom.mjGEOM_ELLIPSOID
    c = hex_rgb(color or PALETTE["body"]) + [1.0]
    up = np.array([0.0, 0.0, 1.0])
    ls, rs, lh, rh = body[5], body[6], body[11], body[12]
    sm = (ls + rs) / 2
    hm = (lh + rh) / 2 if np.isfinite(lh).all() and np.isfinite(rh).all() else sm - 0.5 * up
    ears = body[[3, 4]]
    head = ears.mean(0) if np.isfinite(ears).all() else body[0]
    _add(scn, CAP, [0, 0, 0], sm - 0.05 * up, c, p2=hm - 0.25 * up, r=0.11)      # torso, ends in the counter recess
    _add(scn, CAP, [0, 0, 0], ls, c, p2=rs, r=0.05)                                # shoulders
    _add(scn, CAP, [0, 0, 0], sm, c, p2=head - 0.07 * up, r=0.042)                 # neck
    _add(scn, ELL, [0.085, 0.08, 0.105], head + 0.01 * up, c, specular=0.2, shininess=0.4)
    for s, e, w in ((5, 7, 9), (6, 8, 10)):
        _add(scn, CAP, [0, 0, 0], body[s], c, p2=body[e], r=0.045)                # upper arm
        _add(scn, CAP, [0, 0, 0], body[e], c, p2=body[w], r=0.034)                # forearm
    for side, w in (("left", 9), ("right", 10)):
        if side in hands:
            _add(scn, CAP, [0, 0, 0], body[w], c, p2=hands[side][0], r=0.03)       # wrist to hand
    draw_hands(scn, hands)


# --------------------------------------------------------------------------- cameras
@dataclass
class View:
    lookat: Tuple[float, float, float] = (-0.52, -0.03, COUNTER_HEIGHT + 0.38)
    distance: float = 2.65
    azimuth: float = 160.0
    elevation: float = -18.0


def default_view(counter: Dict[str, float], height: float = COUNTER_HEIGHT, distance: float = 2.65) -> View:
    """The standard ARCADE camera: from across the counter, slightly to the shopper's right."""
    return View(lookat=(counter["x0"] + 0.02, -0.03, height + 0.38), distance=distance, azimuth=160.0,
                elevation=-18.0)


def make_camera(view: View):
    import mujoco
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = view.lookat
    cam.distance, cam.azimuth, cam.elevation = view.distance, view.azimuth, view.elevation
    return cam


def render_rgb(renderer, width: int, height: int) -> np.ndarray:
    """Render at the renderer's (supersampled) size and downsample to width x height."""
    from PIL import Image
    img = renderer.render()
    if img.shape[1] != width or img.shape[0] != height:
        img = np.asarray(Image.fromarray(img).resize((width, height), Image.LANCZOS))
    return img.copy()


def shopper_y(ds: ArcadeHuman, episodes: List[str]) -> float:
    """Median y of the shopper's hip centre over the episodes (counter frame)."""
    ys = []
    for e in episodes:
        b = ds.load(e).body_position.astype(np.float64)
        hm = (b[:, 11] + b[:, 12]) / 2
        ys.append(hm[np.isfinite(hm).all(1), 1])
    ys = np.concatenate(ys) if ys else np.zeros(0)
    return float(np.median(ys)) if len(ys) else -0.12


def closeup_view(ep: Episode, aspect: float = 656 / 880, fovy: float = 30.0) -> View:
    """A fixed camera for the whole episode that frames where the product is held (counter frame
    + COUNTER_HEIGHT), seen from the standard direction."""
    p = ep.object_pose[:, :3].astype(np.float64)
    ok = np.isfinite(p).all(1) & ep["object/valid"].astype(bool)
    held = ok & np.isin(ep["object/state"], (1, 2))
    p = p[held] if held.sum() >= 5 else p[ok]
    if not len(p):
        return View()
    lo, hi = np.percentile(p, 5, axis=0), np.percentile(p, 95, axis=0)
    c = (lo + hi) / 2 + np.array([0.0, 0.0, COUNTER_HEIGHT + 0.02])
    half_v = np.tan(np.radians(fovy / 2))
    half_h = half_v * aspect
    span_h = float(np.hypot(*(hi - lo)[:2])) + 0.28          # where the product is held + room for the hands
    span_v = float(hi[2] - lo[2]) + 0.24
    d = max(span_h / (2 * half_h), span_v / (2 * half_v))
    return View(lookat=tuple(c), distance=float(np.clip(d, 0.7, 1.4)), azimuth=160.0, elevation=-24.0)


# --------------------------------------------------------------------------- episode renderer
@dataclass
class EpisodeScene:
    """Counter + product(s) + shopper for one release; render frames of any of its episodes."""
    ds: ArcadeHuman
    episodes: List[str]
    counter: Optional[Dict[str, float]] = None
    recess: Optional[Dict[str, float]] = field(default_factory=lambda: dict(CAPTURE_RECESS))
    _renderers: Dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        import mujoco
        self.mj = mujoco
        spec = studio_spec()
        self.counter = self.counter or dict(CAPTURE_COUNTER)
        c = self.counter
        if self.recess is not None and "y" not in self.recess:
            self.recess = dict(self.recess, y=shopper_y(self.ds, self.episodes))
        add_counter(spec, c["x0"], c["x1"], c["y0"], c["y1"], recess=self.recess)
        meshes = {}
        for e in self.episodes:
            ep = self.ds.load(e)
            meshes[ep.attrs["product_mesh"]] = os.path.join(self.ds.root, ep.attrs["product_mesh"])
        self.product_body = add_products(spec, meshes)
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        self.offset = np.array([0.0, 0.0, COUNTER_HEIGHT])
        self.view = default_view(c)

    def renderer(self, width: int, height: int):
        key = (width, height)
        if key not in self._renderers:
            self._renderers[key] = self.mj.Renderer(self.model, height * SUPERSAMPLE, width * SUPERSAMPLE,
                                                    max_geom=4000)
        return self._renderers[key]

    def pose(self, ep: Episode, k: int):
        """Place the episode's product at frame k (hidden where its pose is not valid)."""
        mesh = ep.attrs["product_mesh"]
        for m, b in self.product_body.items():
            if m == mesh and ep["object/valid"][k]:
                T = ep.object_matrix()[k].copy()
                T[2, 3] += COUNTER_HEIGHT
                set_mocap(self.model, self.data, b, T)
            else:
                hide_mocap(self.model, self.data, b)
        self.mj.mj_kinematics(self.model, self.data)
        self.mj.mj_camlight(self.model, self.data)

    def panel(self, ep: Episode, k: int, width: int, height: int, view: Optional[View] = None,
              hands_only: bool = False) -> np.ndarray:
        """One rendered view of frame k (call ``pose`` first)."""
        r = self.renderer(width, height)
        r.update_scene(self.data, camera=make_camera(view or self.view))
        hands = {s: ep.hand_position(s)[k].astype(np.float64) + self.offset for s in SIDES}
        if hands_only:
            draw_hands(r.scene, hands)
        else:
            draw_shopper(r.scene, ep.body_position[k].astype(np.float64) + self.offset, hands)
        return render_rgb(r, width, height)

    def frame(self, ep: Episode, k: int, width: int = 1280, height: int = 800, view: Optional[View] = None):
        self.pose(ep, k)
        return self.panel(ep, k, width, height, view)

    def close(self):
        for r in self._renderers.values():
            r.close()
        self._renderers.clear()


def _even(x: float) -> int:
    return int(round(x / 2.0)) * 2


def hero_layout(width: int = 1920, height: int = 1080) -> Dict[str, int]:
    s = width / HERO["width"]
    strip_h = _even(HERO["strip"] * height / HERO["height"])
    scene_w = _even(HERO["scene"] * s)
    gutter = max(2, _even(HERO["gutter"] * s))
    return dict(s=s, W=width, H=height, strip=strip_h, panel_h=height - strip_h, scene=scene_w, gutter=gutter,
                closeup=width - scene_w - gutter)


def episode_timeline(ep: Episode):
    holding = {s: ep[f"interaction/{s}/holding"].astype(bool) for s in SIDES}
    return len(ep), holding, ep.events


def hero_frame(sc: EpisodeScene, ep: Episode, k: int, width: int = 1920, height: int = 1080,
               closeup: Optional[View] = None, layout: str = "hero"):
    """One frame of the episode video: the scene (and, for layout 'hero', a fixed close-up of the hands
    and product) over the timeline strip. Returns a PIL image of width x height."""
    from PIL import Image
    L = hero_layout(width, height)
    s = L["s"]
    fps = float(ep.attrs.get("fps", 19.94))
    sc.pose(ep, k)
    canvas = Image.new("RGB", (width, height), (246, 247, 249))
    if layout == "hero":
        scene = Image.fromarray(sc.panel(ep, k, L["scene"], L["panel_h"]))
        closeup = closeup or closeup_view(ep, L["closeup"] / L["panel_h"])
        close = Image.fromarray(sc.panel(ep, k, L["closeup"], L["panel_h"], closeup, hands_only=True))
        chip(scene, (int(24 * s), int(24 * s)), "Body, hands and product in 3-D", size=int(26 * s))
        chip(close, (int(24 * s), int(24 * s)), "Hands close-up · 21 landmarks each", size=int(26 * s))
        canvas.paste(scene, (0, 0))
        canvas.paste(close, (L["scene"] + L["gutter"], 0))
    else:
        scene = Image.fromarray(sc.panel(ep, k, width, L["panel_h"]))
        chip(scene, (int(24 * s), int(24 * s)), "Body, hands and product in 3-D", size=int(26 * s))
        canvas.paste(scene, (0, 0))
    n, holding, events = episode_timeline(ep)
    canvas.paste(strip(width, L["strip"], n, k, holding, events, fps, ep.task), (0, L["panel_h"]))
    return canvas


def ffmpeg_writer(path: str, width: int, height: int, fps: float, crf: int = 20):
    import shutil
    if shutil.which("ffmpeg") is None:
        raise SystemExit("videos need ffmpeg on PATH (apt install ffmpeg / brew install ffmpeg / conda install ffmpeg)")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    return subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                             f"{width}x{height}", "-r", f"{fps:.3f}", "-i", "-", "-c:v", "libx264", "-preset", "slow",
                             "-pix_fmt", "yuv420p", "-crf", str(crf), "-movflags", "+faststart", path],
                            stdin=subprocess.PIPE)


def mp4_to_webp(mp4: str, webp: str, width: int = 1280, fps: int = 15, quality: int = 70):
    """Animated WebP for README embedding (smaller and sharper than GIF)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vf", f"fps={fps},scale={width}:-1:flags=lanczos",
                    "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", str(quality), "-loop", "0", "-preset", "picture",
                    webp], check=True)


def render_episode_video(root: str, episodes: List[str], out: str, webp: Optional[str] = None,
                         width: int = 1920, height: int = 1080, layout: str = "hero",
                         webp_width: int = 1280) -> str:
    """Studio video of one or more episodes (played one after another) with the timeline strip.

    layout 'hero': the scene plus a close-up of the hands and product; 'scene': the scene only."""
    ds = ArcadeHuman(root)
    unknown = [e for e in episodes if e not in ds.episode_ids]
    if unknown:
        raise SystemExit(f"unknown episodes {unknown}; this release has {', '.join(ds.episode_ids[:6])}"
                         + (", ..." if len(ds) > 6 else ""))
    sc = EpisodeScene(ds, episodes)
    fps = float(ds.info.get("fps", 19.94))
    enc = ffmpeg_writer(out, width, height, fps)
    try:
        for e in episodes:
            ep = ds.load(e)
            L = hero_layout(width, height)
            cv = closeup_view(ep, L["closeup"] / L["panel_h"])
            for k in range(len(ep)):
                img = hero_frame(sc, ep, k, width, height, cv, layout)
                enc.stdin.write(np.asarray(img).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
        sc.close()
    if webp:
        mp4_to_webp(out, webp, width=min(width, webp_width))
    return out


def render_still(root: str, episode: str, out: str, frame: int, width: int = 1920, height: int = 1080,
                 layout: str = "hero") -> str:
    ds = ArcadeHuman(root)
    sc = EpisodeScene(ds, [episode])
    try:
        hero_frame(sc, ds.load(episode), frame, width, height, layout=layout).save(out)
    finally:
        sc.close()
    return out


KIND_LABEL = {"pass": "hand-to-hand pass", "both_hands": "both hands", "one_hand": "{hand} hand",
              "repeated": "picked up twice"}


def render_grid(root: str, episodes: List[str], out: str, cols: int = 3, tile: Tuple[int, int] = (632, 356),
                seconds: float = 8.0, webp: Optional[str] = None, gap: int = 12, webp_width: int = 1280) -> str:
    """Mosaic of several episodes playing at once (each is resampled to the clip length)."""
    from PIL import Image
    ds = ArcadeHuman(root)
    sc = EpisodeScene(ds, episodes)
    v = default_view(sc.counter, distance=2.6)
    eps = [ds.load(e) for e in episodes]
    labels = []
    for ep in eps:
        kind, first, _ = ep.handling()
        labels.append(f"{ep.product} · " + KIND_LABEL[kind].format(hand=first or "right"))
    fps = float(ds.info.get("fps", 19.94))
    rows = (len(eps) + cols - 1) // cols
    W, H = cols * tile[0] + (cols - 1) * gap, rows * tile[1] + (rows - 1) * gap
    W, H = W + W % 2, H + H % 2
    n_out = int(seconds * fps)
    enc = ffmpeg_writer(out, W, H, fps)
    try:
        for t in range(n_out):
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            for i, ep in enumerate(eps):
                k = min(int(t * len(ep) / n_out), len(ep) - 1)
                im = Image.fromarray(sc.frame(ep, k, tile[0], tile[1], v))
                chip(im, (14, tile[1] - 54), labels[i], size=24)
                canvas.paste(im, ((i % cols) * (tile[0] + gap), (i // cols) * (tile[1] + gap)))
            enc.stdin.write(np.asarray(canvas).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
        sc.close()
    if webp:
        mp4_to_webp(out, webp, width=min(W, webp_width))
    return out


#: yaw (deg) that turns each product's printed front towards the camera in the product gallery
PRODUCT_YAW = {"bottle_b": 180.0}


def render_products(root: str, out: str, tile: int = 400) -> str:
    """One studio tile per product (the mesh standing on a counter top), with name and size."""
    import mujoco
    from PIL import Image, ImageDraw
    from .style import font, hex_rgb255
    ds = ArcadeHuman(root)
    tiles = []
    for name, p in sorted(ds.products.items()):
        perm, info = sorted(p["meshes"].items())[0]
        path = os.path.join(ds.root, info["path"])
        V = np.array([[float(x) for x in l.split()[1:4]] for l in open(path, errors="replace") if l.startswith("v ")])
        spec = studio_spec()
        add_counter(spec, -0.3, 0.3, -0.3, 0.3, height=0.04)
        body = add_products(spec, {name: path})[name]
        model = spec.compile()
        data = mujoco.MjData(model)
        T = np.eye(4)
        yaw = np.radians(PRODUCT_YAW.get(name, 0.0))
        T[:2, :2] = [[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]]
        T[2, 3] = 0.04 - V[:, 2].min()
        set_mocap(model, data, body, T)
        mujoco.mj_kinematics(model, data)
        mujoco.mj_camlight(model, data)
        ext = float(np.max(V.max(0) - V.min(0)))
        r = mujoco.Renderer(model, tile * SUPERSAMPLE, tile * SUPERSAMPLE)
        cam = make_camera(View(lookat=(0.0, 0.0, 0.04 + (V[:, 2].max() - V[:, 2].min()) / 2),
                               distance=3.6 * ext + 0.1, azimuth=150.0, elevation=-18.0))
        r.update_scene(data, camera=cam)
        img = Image.fromarray(render_rgb(r, tile, tile))
        r.close()
        dims = p["dims_median_m"]
        size = (f"Ø {2 * dims['r'] * 100:.1f} × {dims['h'] * 100:.1f} cm" if p["shape"] == "cylinder"
                else f"{dims['l'] * 100:.1f} × {dims['w'] * 100:.1f} × {dims['h'] * 100:.1f} cm")
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle([10, tile - 92, tile - 10, tile - 10], radius=14, fill=(255, 255, 255, 230))
        d.text((26, tile - 68), name, fill=hex_rgb255(PALETTE["ink"]), font=font(28, True), anchor="lm")
        d.text((26, tile - 33), size, fill=hex_rgb255(PALETTE["mute"]), font=font(22), anchor="lm")
        tiles.append(img)
    sheet = Image.new("RGB", (tile * len(tiles), tile), (255, 255, 255))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * tile, 0))
    sheet.save(out)
    return out
