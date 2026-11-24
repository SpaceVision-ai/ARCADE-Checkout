#!/usr/bin/env python3
"""Retarget human hand/arm motion to the ROBOTIS FFW-SH5 (swerve base, two 7-DoF arms, two HX5-D20 hands,
2-DoF head) with Pinocchio + Pink IK.

Per episode:
  1. Window: the robot follows the human only inside one window shared by both hands, from buf_pre frames
     before the first grasp to buf_post frames after the last release (no window if the episode has no grasp).
  2. Hand retargeting, per frame inside the window: the robot hand frame and finger joints are fitted to the
     human hand (fingertip positions first, phalanx and palm directions second, subject to the hand rig's joint
     limits, finger self-collision and frame-to-frame continuity; see hand_retarget).
  3. Wrist avoidance: before the first grasp and after the last release only the wrist path is shifted (hand
     shape unchanged) so the hand mesh clears the product and the counter; after the last release the hand
     also retreats from the product.
  4. Idle-hand yielding: a hand that is not holding and not about to grasp moves toward a rest pose beside the
     body when it comes close to the working hand or arm.
  5. Arm + base IK: the swerve base and both arms are solved for the hand-frame targets (torso, counter-edge
     and hand-hand sphere barriers; base back-off picked from dx_grid). Stretches the arm cannot keep up with
     are re-timed (slowed down) and solved again.
  6. Outside the window the arms and fingers stay at the home pose (moving toward a park pose beside the body
     when the other arm or its product comes close). Home ↔ window edge is a quintic joint-space transition
     that matches the window-edge velocity; a transition that dips into the counter, the product or the other
     hand is pushed out, and if it still collides a wrist-space blended path is used instead. The base follows
     slowly during transitions and returns to its start pose after the last window.
  7. Finger refit: from the final wrist poses, the fingers are fitted again to the human fingertips.
The head aims the camera at the primary hand's fingertip. Product contact is not modelled: the hands may touch
the product from the first grasp to the last release (the counter is always a barrier).

Inputs: an ARCADE-Checkout-Human release (--release) and the ROBOTIS FFW-SH5 URDF and meshes (--urdf, --mesh_root).
Outputs: <out_ik>.npz/.json (base, arm and head trajectories, hand targets and errors, time map) and
<out_hand>.npz/.json (finger joint trajectories); see docs/FORMAT.md.

Usage:
  python -m arcade_retarget.ffw_sh5.solver --release REL --jids J03826_left --out_ik build/ik --out_hand build/hand
Normally run through `python -m arcade_retarget.ffw_sh5`, which shards episodes over processes.
"""
import argparse, glob, json, os, sys, time
import numpy as np, pinocchio as pin, pink
from pink import solve_ik
from pink.tasks import FrameTask, PostureTask
from pink.limits import ConfigurationLimit, VelocityLimit
from pink.barriers import BodySphericalBarrier, PositionBarrier
from scipy.optimize import least_squares
from scipy.ndimage import gaussian_filter1d, maximum_filter1d
from scipy.signal import savgol_filter
from arcade_retarget.ffw_sh5 import smooth as SM, product_mesh as PMS, hand_retarget as HR
from arcade_retarget.human_source import HumanSource
from arcade_retarget.paths import DEFAULT_URDF, DEFAULT_MESH_ROOT, counter_config

ap = argparse.ArgumentParser()
ap.add_argument("--release", required=True, help="ARCADE-Checkout-Human release root")
ap.add_argument("--counter", default="auto", help="counter extent JSON, 'auto' (shipped config for the session, else computed from the release) or 'release' (always computed)")
ap.add_argument("--urdf", default=DEFAULT_URDF); ap.add_argument("--mesh_root", default=DEFAULT_MESH_ROOT)
ap.add_argument("--jids", default=""); ap.add_argument("--claim_dir", default="", help="share one episode list across processes: each episode goes to the process that first creates its marker file in this directory"); ap.add_argument("--out_ik", required=True); ap.add_argument("--out_hand", required=True)
ap.add_argument("--fps", type=float, default=19.94); ap.add_argument("--counter_h", type=float, default=0.80, help="floor → counter top height (m)")
# Hand retargeting (hand_retarget): residual scales
ap.add_argument("--sig_tip", type=float, default=0.005, help="fingertip position (m)"); ap.add_argument("--sig_dir", type=float, default=0.15, help="phalanx direction (unit-vector difference)"); ap.add_argument("--sig_palm", type=float, default=0.25, help="palm orientation (rad)")
ap.add_argument("--sig_tq", type=float, default=0.15, help="finger joints, frame to frame (rad)"); ap.add_argument("--sig_tp", type=float, default=0.01, help="wrist position, frame to frame (m)"); ap.add_argument("--sig_tr", type=float, default=0.1, help="wrist rotation, frame to frame (rad)")
ap.add_argument("--g_self", type=float, default=4.0); ap.add_argument("--self_gap", type=float, default=0.0015, help="finger-finger clearance (m)"); ap.add_argument("--self_tol", type=float, default=0.0005, help="re-solve with a finger pair added when its clearance deficit exceeds this (m)")
ap.add_argument("--self_margin", type=float, default=0.008); ap.add_argument("--tau", type=float, default=0.0005)
ap.add_argument("--nfev", type=int, default=30); ap.add_argument("--fq_vmax", type=float, default=0.2, help="max finger joint change per step (rad; URDF 4.8 rad/s = 0.24 per step)")
ap.add_argument("--hand_spacing", type=float, default=0.005); ap.add_argument("--base_spacing", type=float, default=0.008); ap.add_argument("--plan_k", type=int, default=50, help="hand sample points per link for path checks (4× for the hand base link)")
# Wrist shift before the first grasp and after the last release
ap.add_argument("--clear", type=float, default=0.005, help="min clearance between the hand mesh and the product / counter (m)"); ap.add_argument("--fade_n", type=int, default=6, help="the wrist shift fades out over this many frames before the first grasp, reaching 0 at the grasp")
ap.add_argument("--avoid_rounds", type=int, default=4); ap.add_argument("--avoid_vmax", type=float, default=0.01, help="max wrist-shift change per frame (m)"); ap.add_argument("--avoid_max", type=float, default=0.20)
ap.add_argument("--fwd_cost", type=float, default=1.0, help="cost multiplier for avoiding toward the counter (forward)")
ap.add_argument("--retreat", type=float, default=0.10, help="retreat distance after the last release, along product→hand + up (m)"); ap.add_argument("--retreat_n", type=int, default=15); ap.add_argument("--rel_n", type=int, default=3, help="enforce product clearance from this many frames after the last release")
# Idle-hand yielding: a hand that is not holding and has no grasp of its own within approach_w frames moves toward the rest pose when close to the other hand/arm
ap.add_argument("--approach_w", type=int, default=20); ap.add_argument("--yield_d0", type=float, default=0.12); ap.add_argument("--yield_d1", type=float, default=0.25); ap.add_argument("--yield_n", type=int, default=10)
ap.add_argument("--arm_margin", type=float, default=0.02); ap.add_argument("--tr_hh", type=float, default=0.05, help="extra clearance between the two hands' spheres during home ↔ window transitions (m): the human is not followed there, so keep a wide berth (capped by the endpoints if they are closer)")
# Human-following window and motion outside it
ap.add_argument("--buf_pre", type=int, default=20, help="follow the human from this many frames before the first grasp"); ap.add_argument("--buf_post", type=int, default=20, help="follow the human until this many frames after the last release")
ap.add_argument("--idle_home", type=int, default=0, help="if 1, a hand that never grasps in the episode stays at home even inside the window (does not follow the human)")
ap.add_argument("--idle_tol", type=float, default=1e-3, help="leading/trailing steps that move less than this (rad, m) are trimmed from the episode")
ap.add_argument("--edge_pad", type=int, default=90, help="pad this many frozen-time steps before/after the clip (if no hand is holding at that end) so home ↔ window transitions are not compressed (unused steps are trimmed)")
ap.add_argument("--tr_v", type=float, default=0.6, help="max hand speed during home ↔ window transitions (m/s)"); ap.add_argument("--tr_jv", type=float, default=1.5, help="max arm joint speed during home ↔ window transitions (rad/s)")
ap.add_argument("--park_p0", type=float, default=0.03); ap.add_argument("--park_p1", type=float, default=0.10, help="outside the window, a hand at home moves toward the park pose when closer than this to the other hand's product (m)")
ap.add_argument("--tr_min", type=int, default=12, help="min steps for a home ↔ window transition"); ap.add_argument("--tr_base", type=float, default=0.3, help="base speed-limit scale during home ↔ window transitions (the base follows slowly)"); ap.add_argument("--track_warm", type=int, default=10, help="start hand retargeting this many frames before the window (warms up the continuity terms)")
# Arm IK
ap.add_argument("--ramp_n", type=int, default=10, help="frames over which the hand-tracking weight ramps up/down around a holding segment")
ap.add_argument("--w_hand", type=float, default=20.0); ap.add_argument("--w_rot", type=float, default=4.0); ap.add_argument("--w_elbow", type=float, default=2.0); ap.add_argument("--w_post", type=float, default=1.0)
ap.add_argument("--hold_gain", type=float, default=10.0, help="hand-task weight multiplier on holding frames"); ap.add_argument("--iters", type=int, default=30); ap.add_argument("--dt", type=float, default=0.02); ap.add_argument("--ik_tol", type=float, default=1e-10, help="stop iterating a step once the per-iteration joint change is below this (rad; converged)")
ap.add_argument("--dx_grid", type=lambda x: [float(v) for v in x.split(",")], default=[0.0, -0.1, -0.2, -0.3]); ap.add_argument("--smooth", type=int, default=9)
ap.add_argument("--w_base", type=float, default=5.0); ap.add_argument("--base_v", type=float, default=0.5); ap.add_argument("--base_w", type=float, default=1.0)
ap.add_argument("--robot_clear", type=float, default=0.10); ap.add_argument("--counter_near", type=float, default=0.03); ap.add_argument("--counter_far", type=float, default=0.15); ap.add_argument("--counter_side", type=float, default=0.12)
ap.add_argument("--hh_margin", type=float, default=0.02, help="margin added to the min distance of each hand-hand sphere pair (m): the spheres are smaller than the link meshes"); ap.add_argument("--post_hh", type=float, default=0.0, help="extra hand-hand sphere clearance while following the human after the episode's last release (m)"); ap.add_argument("--tr_ramp", type=int, default=6, help="return-to-home transition after the last release: raise the hand-hand clearance requirement to tr_hh over this many steps, regardless of the start pose")
ap.add_argument("--home_iters", type=int, default=200)
ap.add_argument("--rt_gain", type=float, default=0.8, help="do not slow a frame further if its error did not drop below this fraction of the previous round's"); ap.add_argument("--retime_rounds", type=int, default=3); ap.add_argument("--rt_tol", type=float, default=15.0); ap.add_argument("--rt_k", type=float, default=15.0); ap.add_argument("--rt_step", type=float, default=2.0); ap.add_argument("--rt_max", type=float, default=4.0)
ap.add_argument("--rt_max_free", type=float, default=8.0, help="max slow-down factor on frames where both hands are outside the window (nothing to follow)")
A = ap.parse_args()

# ARCADE-Checkout-Human data is already in the counter frame: identity transform, counter top at z = 0
Tc = np.eye(4); Z0 = 0.0
SRC = HumanSource(A.release, [j for j in A.jids.split(",") if j] or None)
TRI, VAL = SRC.TRI, SRC.VAL
S3, CL = SRC.holding, SRC.clips
SIDES = {"left": dict(s="l", sh=5, el=7, hand=91), "right": dict(s="r", sh=6, el=8, hand=112)}
ARM = ["arm_%s_joint%d" % (s, i) for s in ("l", "r") for i in range(1, 8)]
Zc = np.array([0, 0, A.counter_h])   # canonical (counter) frame → model world
def can(x): return x @ Tc[:3, :3].T + Tc[:3, 3] - np.array([0, 0, Z0])
def cosr(u): return 0.5 - 0.5 * np.cos(np.pi * np.clip(u, 0, 1))

# Robot models: full = swerve base (planar joint) + whole body, hm = fixed-base model for finger kinematics
full = pin.buildModelFromUrdf(A.urdf, pin.JointModelPlanar())
hm = pin.buildModelFromUrdf(A.urdf); hd = hm.createData(); pin.forwardKinematics(hm, hd, pin.neutral(hm)); pin.updateFramePlacements(hm, hd)
def Fh(n): return hd.oMf[hm.getFrameId(n)]
UPPER = float(np.linalg.norm(Fh("arm_l_link4").translation - Fh("arm_l_link2").translation))
FIT = dict(sig_tip=A.sig_tip, sig_dir=A.sig_dir, sig_palm=A.sig_palm, sig_tq=A.sig_tq, sig_tp=A.sig_tp, sig_tr=A.sig_tr, g_self=A.g_self, self_gap=A.self_gap, self_tol=A.self_tol, self_margin=A.self_margin, tau=A.tau, nfev=A.nfev)
RIG = {sd: HR.HandRig(hm, A.urdf, A.mesh_root, sd, FIT, spacing=A.hand_spacing, base_spacing=A.base_spacing, plan_k=A.plan_k) for sd in SIDES}


def kp_track(f0, n, idx):
    """Human keypoint trajectory (canonical frame); missing frames are linearly interpolated."""
    fs = np.arange(f0, f0 + n); P_ = can(TRI[fs, idx]); m = VAL[fs, idx] & np.isfinite(P_).all(1)
    if m.sum() < 2: return None
    return np.stack([np.interp(np.arange(n), np.nonzero(m)[0], P_[m, d]) for d in range(3)], 1)
def human_arms(f0, n):
    """Per-side human shoulder and elbow trajectories (for the elbow-direction target)."""
    tr = {}
    for side, c in SIDES.items():
        K = {k: kp_track(f0, n, i) for k, i in (("sh", c["sh"]), ("el", c["el"]))}
        if any(v is None for v in K.values()): return None
        w_ = min(A.smooth if A.smooth % 2 else A.smooth + 1, n - (1 - n % 2))
        if A.smooth > 1 and w_ >= 5: K = {k: savgol_filter(v, w_, 2, axis=0) for k, v in K.items()}
        tr[side] = K
    return tr
def human_hand(side, f0, n):
    """Human hand 21-keypoint trajectory (canonical frame), or None if missing."""
    h = SIDES[side]["hand"]; X = [kp_track(f0, n, h + i) for i in range(21)]
    return None if any(x is None for x in X) else np.stack(X, 1)

def load_obj(jid, f0, n):
    """Per-frame product pose (canonical frame; missing frames take the nearest valid frame) and the product distance field."""
    o = SRC.OBJ.get(jid)
    if o is None: return None
    of = {int(f): i for i, f in enumerate(o.frames)}; T = np.full((n, 4, 4), np.nan)
    for t in range(n):
        i = of.get(f0 + t)
        if i is not None and np.all(np.isfinite(o.T[i])): T[t] = o.T[i]
    ok = np.all(np.isfinite(T.reshape(n, -1)), 1)
    if not ok.any(): return None
    idx = np.nonzero(ok)[0]; T = T[idx[np.abs(np.arange(n)[:, None] - idx[None]).argmin(1)]]
    return T, PMS.field(SRC.product_meta(jid))

_CB = None
def counter_box():
    """Counter extent shared by all episodes (canonical frame)."""
    global _CB
    if _CB is None:
        _CB = counter_config(A.counter, SRC.ds.info.get("session")) or SRC.counter_box(A.counter_near, A.counter_far, A.counter_side)
    return _CB
def on_counter(X):
    cb = counter_box(); return (X[:, 0] >= cb["x0"]) & (X[:, 0] <= cb["x1"]) & (X[:, 1] >= cb["y0"]) & (X[:, 1] <= cb["y1"])


# Wrist shift before the first grasp and after the last release: only translates the robot hand, keeping the human hand shape
def zero_dist(zero):
    """Per-frame distance (frames) to the nearest frame whose shift must be 0 (first grasp to last release); inf if none."""
    k = np.arange(len(zero)); z = np.nonzero(zero)[0]
    return np.abs(k[:, None] - z[None]).min(1).astype(float) if len(z) else np.full(len(zero), np.inf)
def envelope(need, zd, vmax):
    """Per-frame avoidance vectors → smooth offset (the magnitude spreads to neighbouring frames and decays with slope vmax toward the zero span)."""
    n = len(need); k = np.arange(n); mag = np.linalg.norm(need, axis=1); ts = np.nonzero(mag > 0)[0]
    if len(ts) == 0: return np.zeros((n, 3))
    ramp = lambda h: max(6, int(np.ceil(np.pi / 2 * h / vmax))); out = np.zeros(n)
    for t in ts: out = np.maximum(out, mag[t] * cosr(1 - np.abs(k - t) / ramp(mag[t])))
    for t1, t2 in zip(ts[:-1], ts[1:]):   # no dip between two nearby demands
        if t2 - t1 <= 2 * ramp(min(mag[t1], mag[t2])): out[t1:t2 + 1] = np.maximum(out[t1:t2 + 1], min(mag[t1], mag[t2]))
    wk = np.exp(-0.5 * ((k[:, None] - ts[None, :]) / 6.0) ** 2) * mag[ts][None, :]; Dv = wk @ (need[ts] / mag[ts][:, None]); Dv /= np.maximum(np.linalg.norm(Dv, axis=1, keepdims=True), 1e-9)
    return np.minimum(out, vmax * zd)[:, None] * Dv
def retreat(P, obj, bl, n):
    """Offset that smoothly retreats by `retreat` after the last release (bl), along product→hand + up."""
    out = np.zeros((n, 3)); up = np.array([0, 0, 1.0])
    if bl is None or bl >= n: return out
    u = P[bl - 1] - obj[0][bl - 1][:3, 3] if obj is not None else up; u = u / max(np.linalg.norm(u), 1e-9); d = (u + up) / max(np.linalg.norm(u + up), 1e-9)
    t = np.arange(n); return np.where(t >= bl, A.retreat * cosr((t - bl + 1) / A.retreat_n), 0.0)[:, None] * d
def shift(side, P, R, Q, obj, g, bl, fwd, win):
    """Wrist path offset (n,3): inside the window (win), up to fade_n frames before the first grasp (g) and from rel_n frames after the last release (bl), keep the hand mesh `clear` away from the product and counter (after the release, on top of the retreat);
    zero from the first grasp to the last release (product contact allowed). The counter is avoided by lifting only, over the whole window. Returns (offset, initial touching frames, remaining touching frames)."""
    n = len(P); rig = RIG[side]; up = np.array([0, 0, 1.0]); t_ = np.arange(n); MP = {}
    def mp(t):
        if t not in MP: MP[t] = rig.mesh_pts(Q[t])[0]
        return MP[t]
    zero = (t_ >= g) & (t_ < bl); zd = zero_dist(zero)
    ts = np.nonzero(win & ((t_ < g - A.fade_n) | (t_ >= bl + A.rel_n)))[0]
    def counter_need(X): oc = on_counter(X); return max(0.0, A.clear - X[oc, 2].min()) if oc.any() else 0.0
    base = retreat(P, obj, bl, n); off = np.zeros((n, 3)); touch0 = None
    for _ in range(A.avoid_rounds):
        need = np.zeros((n, 3)); touch = 0
        for t in ts:
            X = mp(t) @ R[t].T + P[t] + base[t] + off[t]; vec = np.zeros(3); To = obj[0][t] if obj is not None else None
            dmin = (lambda v: float(obj[1]((X + v - To[:3, 3]) @ To[:3, :3]).min())) if To is not None else None
            if dmin is not None and dmin(0) < A.clear:
                touch += 1; Lk = (X - To[:3, 3]) @ To[:3, :3]; i = int(np.argmin(obj[1](Lk))); gn = To[:3, :3] @ obj[1].normal(Lk[i]); gn[2] = max(gn[2], 0.0)
                out_ = gn / np.linalg.norm(gn) if np.linalg.norm(gn) > 1e-9 else up; best = None
                for c in (out_, up, -fwd, out_ + up, out_ - fwd, up - fwd, out_ + up - fwd):   # shortest of: out of the product / up / back (moving toward the counter costs more)
                    c = c / max(np.linalg.norm(c), 1e-9)
                    if c[2] < -0.2: continue
                    s_ = next((s for s in np.arange(0.005, A.avoid_max + 1e-9, 0.005) if dmin(s * c) >= A.clear and counter_need(X + s * c) == 0.0), None)
                    if s_ is not None and (best is None or s_ * (1 + A.fwd_cost * max(0.0, c @ fwd)) < best[0]): best = (s_ * (1 + A.fwd_cost * max(0.0, c @ fwd)), s_ * c)
                vec = best[1] if best is not None else A.avoid_max * (up - fwd) / np.sqrt(2)
            cz = counter_need(X)
            if cz > 0: touch += 1; vec[2] = max(vec[2], cz)
            need[t] = vec
        touch0 = touch if touch0 is None else touch0
        if touch == 0: break
        off = off + envelope(need, zd, A.avoid_vmax); nm = np.linalg.norm(off, axis=1, keepdims=True); off *= np.minimum(1.0, A.avoid_max / np.maximum(nm, 1e-9))
    off = off + base; lift = np.array([[0, 0, counter_need(mp(t) @ R[t].T + P[t] + off[t]) if win[t] else 0.0] for t in range(n)])   # counter: lift only, over the whole window
    return off + envelope(lift, np.full(n, np.inf), A.avoid_vmax), touch0 or 0, touch

def free_mask(segs, n):
    """Idle hand: not holding, and its next grasp is not within approach_w frames."""
    t = np.arange(n); busy = np.zeros(n, bool)
    for a, b in segs: busy |= (t >= a - A.approach_w) & (t < b)
    return ~busy
def seg_dist(X, S0, S1):
    d = S1 - S0; u = np.clip(((X - S0) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-12), 0, 1); return np.linalg.norm(X - S0 - u[..., None] * d, axis=-1)
def spread(y_raw, n_, hold=False):
    """Spread weight peaks smoothly over n_ steps on each side (with hold, no dip between two peaks within 2 n_)."""
    t = np.arange(len(y_raw)); y = np.zeros(len(y_raw)); ks = np.nonzero(y_raw > 0)[0]
    for k in ks: y = np.maximum(y, y_raw[k] * cosr(1 - np.abs(t - k) / n_))
    if hold:
        for k1, k2 in zip(ks[:-1], ks[1:]):
            if 1 < k2 - k1 <= 2 * n_: y[k1:k2 + 1] = np.maximum(y[k1:k2 + 1], min(y_raw[k1], y_raw[k2]))
    return y
def yield_w(sd, PL, tr, segs, n, win):
    """Blend weight toward the rest pose inside the window (0-1): rises (over yield_n frames) when the idle hand is closer than yield_d1 to the working other hand/arm (shoulder→hand segment). Falls to 0 toward frames where the hand is not idle."""
    o = "left" if sd == "right" else "right"; F, Fo = free_mask(segs[sd], n), free_mask(segs[o], n)
    p = PL[sd]["p"] + PL[sd]["off"]; po = PL[o]["p"] + PL[o]["off"]
    d = seg_dist(p, tr[o]["sh"], po); y_raw = np.clip((A.yield_d1 - d) / (A.yield_d1 - A.yield_d0), 0, 1) * (F & ~Fo) * win[sd]
    return np.minimum(spread(y_raw, A.yield_n), zero_dist(~F) / A.yield_n) * win[sd], F
def windows(segs, n):
    """Frames that follow the human (shared by both hands): from buf_pre before the episode's first grasp to buf_post after its last release; none if there is no grasp."""
    v = [x for sv in segs.values() for x in sv]; t = np.arange(n)
    w = (t >= min(a for a, _ in v) - A.buf_pre) & (t < max(b for _, b in v) + A.buf_post) if v else np.zeros(n, bool); return {sd: w.copy() if segs[sd] or not A.idle_home else np.zeros(n, bool) for sd in segs}

def active_span(X):
    """From one step before leaving the initial pose to one step after reaching the final pose (drops the idle leading/trailing spans)."""
    m0, m1 = np.nonzero(np.abs(X - X[0]).max(1) > A.idle_tol)[0], np.nonzero(np.abs(X - X[-1]).max(1) > A.idle_tol)[0]
    return (0, len(X) - 1) if not len(m0) else (max(int(m0[0]) - 1, 0), min(int(m1[-1]) + 1, len(X) - 1))

def interact_w(segs, n):
    """Hand-tracking weight (0-1): 1 on holding segments, ramping up/down over ramp_n frames on each side."""
    w = np.zeros(n); t = np.arange(n)
    for a, b in segs:
        w[a:b] = 1.0; w = np.maximum(w, np.where((t >= a - A.ramp_n) & (t < a), cosr((t - (a - A.ramp_n) + 1) / A.ramp_n), 0.0)); w = np.maximum(w, np.where((t >= b) & (t < b + A.ramp_n), 1 - cosr((t - b + 1) / A.ramp_n), 0.0))
    return w


# Arm IK. Faster drop-in replacements (same results) for Pink internals: barrier cache comparison, task weighting, frame-name lookup, zero barrier objective terms
import pink.barriers.barrier as _pbb, pink.tasks.task as _ptk, pink.configuration as _pcf
class _NP:
    def __getattr__(self, k): return getattr(np, k)
    @staticmethod
    def allclose(a, b, rtol=1e-05, atol=1e-08): return bool(np.all(np.abs(a - b) <= atol + rtol * np.abs(b)))
_pbb.np = _NP()
def _task_qp(self, configuration):
    if isinstance(self, FrameTask):   # read the frame pose only once
        m, d = configuration.model, configuration.data; i = _fid(m, self.frame); T = d.oMf[i]
        J = -pin.Jlog6(self.transform_target_to_world.actInv(T)) @ pin.getFrameJacobian(m, d, i, pin.ReferenceFrame.LOCAL); e = -self.gain * pin.log(T.actInv(self.transform_target_to_world)).vector
    else: J = self.compute_jacobian(configuration); e = -self.gain * self.compute_error(configuration)
    k = J.shape[0]
    w = np.ones(k) if self.cost is None else np.full(k, self.cost) if isinstance(self.cost, float) else np.asarray(self.cost, float)
    WJ = w[:, None] * J; We = w * e; mu = self.lm_damping * We @ We
    return WJ.T @ WJ + mu * configuration.tangent.eye, -We.T @ WJ
_ptk.Task.compute_qp_objective = _task_qp
def _fid(model, name):
    try: c = model._arcade_fid
    except AttributeError: c = model._arcade_fid = {}
    i = c.get(name)
    if i is None: i = c[name] = model.getFrameId(name)
    return i
def _frame_T(self, frame):
    try: return self.data.oMf[_fid(self.model, frame)].copy()
    except IndexError as e: raise _pcf.FrameNotFound(frame, self.model.frames) from e
def _frame_J(self, frame):
    i = _fid(self.model, frame)
    if i >= self.model.nframes: raise _pcf.FrameNotFound(frame, self.model.frames)
    return pin.getFrameJacobian(self.model, self.data, i, pin.ReferenceFrame.LOCAL)
_pcf.Configuration.get_transform_frame_to_world = _frame_T; _pcf.Configuration.get_frame_jacobian = _frame_J
def _qp_objective(configuration, tasks, damping, barriers=None):
    H = damping * configuration.tangent.eye; c = configuration.tangent.zeros.copy()
    for task in tasks: H_, c_ = task.compute_qp_objective(configuration); H += H_; c += c_
    for b in barriers or []:   # barriers with safe_displacement_gain 0 have a zero objective term (the Jacobian cache is filled on the inequality side under the same condition)
        if b.safe_displacement_gain > 1e-6: H_, c_ = b.compute_qp_objective(configuration); H += H_; c += c_
    return H, c
setattr(sys.modules["pink.solve_ik"], "__compute_qp_objective", _qp_objective)
import pink.barriers.body_spherical_barrier as _pbs
def _bsb_barrier(self, configuration):
    m, oMf = configuration.model, configuration.data.oMf; p1, p2 = oMf[_fid(m, self.frames[0])].translation, oMf[_fid(m, self.frames[1])].translation
    return np.array([(p1 - p2).dot(p1 - p2) - self.d_min ** 2])
def _bsb_jac(self, configuration):
    m, d = configuration.model, configuration.data; i1, i2 = _fid(m, self.frames[0]), _fid(m, self.frames[1]); T1, T2 = d.oMf[i1], d.oMf[i2]
    J1 = T1.rotation @ pin.getFrameJacobian(m, d, i1, pin.ReferenceFrame.LOCAL)[:3]; J2 = T2.rotation @ pin.getFrameJacobian(m, d, i2, pin.ReferenceFrame.LOCAL)[:3]
    return (2 * (T1.translation - T2.translation)).T @ (J1 - J2)
_pbs.BodySphericalBarrier.compute_barrier = _bsb_barrier; _pbs.BodySphericalBarrier.compute_jacobian = _bsb_jac
TORSO = [((0.0, y, z), 0.09) for y in (-0.08, 0.0, 0.08) for z in (0.0, -0.12)] + [((0.0, 0.0, -0.24), 0.07)]
FRONT = [("arm_base_link", (0.09, y, 0.0)) for y in (-0.15, 0.0, 0.15)]
HAND_R = 0.045; J7_LIM = np.radians(90.55)
TIPF = ("tipT", 0.02, (0,)), ("tipF", 0.025, (1, 2)), ("tipR", 0.025, (3, 4))   # fingertip spheres: centroid of thumb / index+middle / ring+little tips (moved with the fingers every frame)
HHF = {sd: [("mcp_%s" % sd, HAND_R), ("hx5_d20_%s_base" % sd, HAND_R), ("fing_%s" % sd, 0.04), ("arm_%s_link6" % SIDES[sd]["s"], 0.04), ("arm_%s_link7" % SIDES[sd]["s"], 0.04)] + [("%s_%s" % (k, sd), r) for k, r, _ in TIPF] for sd in SIDES}   # hand-hand spheres
HH = [(a, b, ra + rb + A.hh_margin) for a, ra in HHF["left"] for b, rb in HHF["right"]]
ARMS = {sd: [("arm_%s_link%d" % (SIDES[sd]["s"], k), r) for k, r in ((3, 0.06), (4, 0.06), (5, 0.05))] for sd in SIDES}   # arm spheres (upper arm, elbow, forearm)
AH = {sd: [(a, b, ra + rb + A.arm_margin) for a, ra in HHF[sd] for b, rb in ARMS["left" if sd == "right" else "right"]] for sd in SIDES}   # idle hand ↔ other arm
class HoldBarrier(BodySphericalBarrier):
    """For pairs already in penetration, only prevent them from getting closer (used when demanding full recovery makes the QP infeasible)."""
    def compute_barrier(self, configuration): return np.maximum(super().compute_barrier(configuration), 0.0)
HOME = {"left": (0.30, 0.18, 1.15), "right": (0.30, -0.18, 1.15)}; HOME_B = np.stack([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]], 1)
REST = {"left": (0.0, 0.35, 0.88), "right": (0.0, -0.35, 0.88)}; REST_R = {sd: Fh("arm_%s_link7" % SIDES[sd]["s"]).rotation.copy() for sd in SIDES}   # rest pose: hand lowered beside the body, above counter height (wrist orientation of the zero-pose arm)
PARK = {"left": (-0.05, 0.30, 1.10), "right": (-0.05, -0.30, 1.10)}   # park pose for an arm outside the window: beside/behind the body within reach; with the arm joints fixed, the fingers stay above the counter top and products even when the base moves toward the counter
HEAD = ("head_joint1", "head_joint2"); CAM = "zed_camera_center"
def arm_model(iters):
    keep = set(ARM) | {"root_joint"}; lock = [full.getJointId(full.names[i]) for i in range(1, full.njoints) if full.names[i] not in keep]
    m = pin.buildReducedModel(full, lock, pin.neutral(full))
    for i, (o, _) in enumerate(TORSO):
        fid = m.getFrameId("arm_base_link"); fr = m.frames[fid]; m.addFrame(pin.Frame("torso_%d" % i, fr.parentJoint, fid, fr.placement * pin.SE3(np.eye(3), np.array(o)), pin.FrameType.OP_FRAME))
    for i, (ln, o) in enumerate(FRONT):
        fid = m.getFrameId(ln); fr = m.frames[fid]; m.addFrame(pin.Frame("front_%d" % i, fr.parentJoint, fid, fr.placement * pin.SE3(np.eye(3), np.array(o)), pin.FrameType.OP_FRAME))
    jr = m.joints[m.getJointId("root_joint")]; m.velocityLimit[jr.idx_v:jr.idx_v + 3] = np.array([A.base_v, A.base_v, A.base_w]) / (A.fps * iters * A.dt)   # base speed limits in solver units
    for s_ in ("l", "r"):   # wrist joint7: URDF and USD ranges differ (mirrored left/right); use the intersection of both
        k_ = m.joints[m.getJointId("arm_%s_joint7" % s_)].idx_q; m.lowerPositionLimit[k_] = max(m.lowerPositionLimit[k_], -J7_LIM); m.upperPositionLimit[k_] = min(m.upperPositionLimit[k_], J7_LIM)
    for side, c in SIDES.items():
        rig = RIG[side]; fid = m.getFrameId("arm_%s_link7" % c["s"]); fr = m.frames[fid]
        m.addFrame(pin.Frame("mcp_%s" % side, fr.parentJoint, fid, fr.placement * pin.SE3(np.eye(3), rig.mcp), pin.FrameType.OP_FRAME))
        m.addFrame(pin.Frame("fing_%s" % side, fr.parentJoint, fid, fr.placement * pin.SE3(np.eye(3), rig.mcp + 0.06 * rig.B[:, 0]), pin.FrameType.OP_FRAME))
        for k, _, _ in TIPF: m.addFrame(pin.Frame("%s_%s" % (k, side), fr.parentJoint, fid, fr.placement * pin.SE3(np.eye(3), rig.mcp), pin.FrameType.OP_FRAME))
    return m
def mj(u):
    """Quintic blend basis: 0→1 position, end-velocity and start-velocity terms (zero acceleration at both ends)."""
    u = np.clip(u, 0, 1); return 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5, -4 * u ** 3 + 7 * u ** 4 - 3 * u ** 5, u - 6 * u ** 3 + 8 * u ** 4 - 3 * u ** 5
def mj_d(u):
    u = np.clip(u, 0, 1); return 30 * u ** 2 - 60 * u ** 3 + 30 * u ** 4, -12 * u ** 2 + 28 * u ** 3 - 15 * u ** 4, 1 - 18 * u ** 2 + 32 * u ** 3 - 15 * u ** 4
def wrap(a): return (a + np.pi) % (2 * np.pi) - np.pi
def end_vel(v, d, L):
    """Blend end velocity (per step): only the component along the move, capped so the blend does not overshoot and come back."""
    return np.where(v * d > 0, np.sign(v) * np.minimum(np.abs(v), 1.5 * np.abs(d) / max(L, 1)), 0.0)
def need_steps(dq, v, dp, db, into):
    """Steps needed to join home and a window edge at a natural speed: within arm joint tr_jv, hand tr_v and 0.8 × base limits (including the end-velocity matching term)."""
    T0 = max(A.tr_min, 1.875 * np.abs(dq).max() * A.fps / A.tr_jv, 1.875 * dp * A.fps / A.tr_v, 1.875 * np.linalg.norm(db[:2]) * A.fps / (0.8 * A.base_v), 1.875 * abs(db[2]) * A.fps / (0.8 * A.base_w))
    u = np.linspace(0, 1, 41); d5, d4, d1 = mj_d(u); T = T0
    while T < 4 * T0:
        sp = np.abs((1 if into else -1) * np.outer(d5, dq) / T + np.outer(d4 if into else d1, end_vel(v, dq, T))).max()
        if sp <= A.tr_jv / A.fps: break
        T *= 1.1
    return int(np.ceil(T))
def ik_solve(TG, tr, WIN, yaw, xy0, x_edge, dx, step=1, iters=None, prod=None, transit=True, post_m=None):
    """Inside the window (WIN[side] true = that hand follows the human), solve base + arms for hand-frame targets TG[side] = (p, R, hand-tracking weight, fingers, rest-pose weight, idle flag).
    Outside the window an arm is held at home joints (toward the park pose when the other arm or its product is close); home ↔ window edge is a quintic joint-space blend (matching the window-edge velocity); if that path
    goes further into the counter, product or other hand it is pushed out, and if violations remain the first pass's wrist-space blended path is used. The base follows slowly during blends and returns to its start after the last window. prod = (product pose (n,4,4), distance field): for path checks.
    Returns (model, joints, errors, base xy, root index, barrier fallback counts, per-side transit info, targets used, per-side human weight)."""
    iters = iters or A.iters; n = len(WIN["left"]); Rb = pin.utils.rpyToMatrix(0, 0, yaw); m = arm_model(iters * step); d2 = m.createData()
    ab0 = Fh("arm_base_link").translation; front_ab = max(Rb[0, :2] @ np.array(o[:2]) + ab0[0] for _, o in FRONT)
    xy = xy0 - (Rb @ ab0)[:2] + Rb[:2, 0] * dx; xy[0] = min(xy[0], x_edge - front_ab - 0.01)
    jr = m.joints[m.getJointId("root_joint")].idx_q; jv = m.joints[m.getJointId("root_joint")].idx_v
    base = FrameTask("base_link", position_cost=A.w_base, orientation_cost=0.5 * A.w_base, lm_damping=1.0); base.set_target(pin.SE3(Rb, np.array([xy[0], xy[1], 0.0])))
    hand = {s: FrameTask("mcp_%s" % s, position_cost=A.w_hand, orientation_cost=A.w_rot, lm_damping=1.0) for s in SIDES}
    elb = {s: FrameTask("arm_%s_link4" % SIDES[s]["s"], position_cost=A.w_elbow, orientation_cost=0.0, lm_damping=1.0) for s in SIDES}
    post = PostureTask(cost=A.w_post); lim = [ConfigurationLimit(m), VelocityLimit(m)]
    q0 = pin.neutral(m); q0[jr:jr + 4] = [xy[0], xy[1], np.cos(yaw), np.sin(yaw)]
    for s_ in ("l", "r"): q0[m.joints[m.getJointId("arm_%s_joint4" % s_)].idx_q] = -1.2
    IA = {sd: np.array([m.joints[m.getJointId("arm_%s_joint%d" % (SIDES[sd]["s"], j))].idx_q for j in range(1, 8)]) for sd in SIDES}
    IV = {sd: np.array([m.joints[m.getJointId("arm_%s_joint%d" % (SIDES[sd]["s"], j))].idx_v for j in range(1, 8)]) for sd in SIDES}; VL = m.velocityLimit.copy()
    hfr = [(f_, HAND_R) for sd in SIDES for f_ in ("mcp_%s" % sd, "hx5_d20_%s_base" % sd)] + [("arm_%s_link6" % SIDES[sd]["s"], 0.04) for sd in SIDES]
    pairs = [(f_, "torso_%d" % i, r + hr) for f_, hr in hfr for i, (_, r) in enumerate(TORSO)]
    bnames = sorted({f_ for a, b_, _ in pairs for f_ in (a, b_)} | {f_ for a, b_, _ in HH + AH["left"] + AH["right"] for f_ in (a, b_)})
    off_mcp = {sd: {f_: (np.zeros(3) if f_.startswith("mcp") else RIG[sd].mcp2hb.translation if f_.startswith("hx5") else 0.06 * RIG[sd].B[:, 0] if f_.startswith("fing") else -RIG[sd].mcp if f_.startswith("arm_") and f_.endswith("7") else None) for f_, _ in HHF[sd]} for sd in SIDES}
    TIP = {sd: RIG[sd].rows(TG[sd][3], tips=True)[1] for sd in SIDES}   # fingertips of the target finger joints (hand frame)
    tfid = {(k, sd): m.getFrameId("%s_%s" % (k, sd)) for k, _, _ in TIPF for sd in SIDES}; l7p = {sd: m.frames[m.getFrameId("arm_%s_link7" % SIDES[sd]["s"])].placement for sd in SIDES}
    def tip_frames(i):
        for k, _, ix in TIPF:
            for sd in SIDES:
                o = TIP[sd][i][list(ix)].mean(0); off_mcp[sd]["%s_%s" % (k, sd)] = o; m.frames[tfid[(k, sd)]].placement = l7p[sd] * pin.SE3(np.eye(3), RIG[sd].mcp + o)
        cfg.update(cfg.q)
    tasks = [hand["left"], hand["right"], elb["left"], elb["right"], post, base]; nfb = np.zeros(3, int)
    pbar = {(a, b_): BodySphericalBarrier((a, b_), d_min=dm, gain=2.0, safe_displacement_gain=0.0) for a, b_, dm in pairs}
    fbar = [PositionBarrier("front_%d" % i, indices=[0], p_max=np.array([x_edge]), gain=2.0) for i in range(len(FRONT))]
    Tb_home = pin.SE3(Rb, np.array([xy[0], xy[1], 0.0])); cfg = pink.Configuration(m, m.createData(), q0)
    idx = list(range(0, n, step)); K = len(idx); Q = np.zeros((K, m.nq)); err = {s: np.zeros((K, 3)) for s in SIDES}; tgt = {s: np.full((K, 4, 4), np.nan) for s in SIDES}   # hand targets actually used
    win = {sd: np.asarray(WIN[sd], bool)[idx] for sd in SIDES}; act = win["left"] | win["right"]
    def hr_pose(side, y, park=False):
        """Hand pose and elbow direction between home (y=0) and rest (y=1), relative to the initial base; with park, the higher park pose used outside the window."""
        sg = 1.0 if side == "left" else -1.0
        p0 = Tb_home.act(np.array(HOME[side])); R0 = Rb @ HOME_B @ RIG[side].B.T; u0 = Rb @ np.array([0.0, 0.25 * sg, -1.0]); u0 /= np.linalg.norm(u0)
        pr = Tb_home.act(np.array((PARK if park else REST)[side])); Rr = Rb @ REST_R[side]; ur = Rb @ np.array([0.0, 0.3 * sg, -1.0]); ur /= np.linalg.norm(ur)
        u = (1 - y) * u0 + y * ur; return (1 - y) * p0 + y * pr, R0 @ pin.exp3(y * pin.log3(R0.T @ Rr)), u / np.linalg.norm(u)
    def targets(i, outs=(), fix=None, g=True):
        """Hands inside the window: human hand target (idle hands blended with the rest pose). outs: hands with tasks disabled (joints fixed). fix[side] = (hand SE3, elbow direction)."""
        tg = {}
        for side in SIDES:
            s_ = SIDES[side]["s"]
            if side in outs:
                hand[side].set_position_cost(0.0); hand[side].set_orientation_cost(0.0); elb[side].set_position_cost(0.0); T_ = cfg.get_transform_frame_to_world("mcp_%s" % side)
                tg[side] = (T_.translation.copy(), T_.rotation.copy(), cfg.get_transform_frame_to_world("arm_%s_link4" % s_).translation.copy()); continue
            if fix is not None and side in fix:
                (Tt, u_) = fix[side]; p_t, R_t = Tt.translation, Tt.rotation
                hand[side].set_position_cost(A.w_hand); hand[side].set_orientation_cost(A.w_rot); elb[side].set_position_cost(A.w_elbow)
            else:
                p_t, R_t, g_ = TG[side][0][i] + Zc, TG[side][1][i], TG[side][2][i] if g else 0.0
                hand[side].set_position_cost(A.w_hand * (1 + (A.hold_gain - 1) * g_)); hand[side].set_orientation_cost(A.w_rot * (1 + (A.hold_gain - 1) * g_)); elb[side].set_position_cost(A.w_elbow * (1 - 0.9 * g_))
                u_ = tr[side]["el"][i] - tr[side]["sh"][i]; u_ = u_ / max(np.linalg.norm(u_), 1e-6); y_ = TG[side][4][i]
                if y_ > 0:   # idle hand: blend with the rest pose
                    pr_, Rr_, ur_ = hr_pose(side, 1.0)
                    p_t = (1 - y_) * p_t + y_ * pr_; R_t = R_t @ pin.exp3(y_ * pin.log3(R_t.T @ Rr_)); u_ = (1 - y_) * u_ + y_ * ur_; u_ /= np.linalg.norm(u_)
            hand[side].set_target(pin.SE3(R_t, p_t))
            e_h = cfg.get_transform_frame_to_world("arm_%s_link2" % s_).translation + UPPER * u_
            Te = cfg.get_transform_frame_to_world("arm_%s_link4" % s_).copy(); Te.translation = e_h; elb[side].set_target(Te); tg[side] = (p_t, R_t, e_h)
        return tg
    def iterate(i, tg, n_it, g=True):
        tip_frames(i); post.set_target(cfg.q.copy()); PF = {f_: cfg.get_transform_frame_to_world(f_).translation for f_ in bnames}
        bar = fbar + [pbar[(a, b_)] for a, b_, dm in pairs if np.linalg.norm(PF[a] - PF[b_]) < dm + 0.10]
        fl, fr_ = TG["left"][5][i] > 0.5, TG["right"][5][i] > 0.5; ah = AH["left"] if fl and not fr_ else AH["right"] if fr_ and not fl else []   # if only one hand is idle, it keeps clear of the other arm
        bar = bar + [BodySphericalBarrier((a, b_), d_min=dm, gain=2.0, safe_displacement_gain=0.0) for a, b_, dm in ah if np.linalg.norm(PF[a] - PF[b_]) < dm + 0.10]
        both = g and min(TG[sd][2][i] for sd in SIDES) > 0.0   # only on frames where both hands hold (handover) may the hands come as close as the human's
        def plan_pos(sd, f_):
            o = off_mcp[sd][f_]; return tg[sd][0] + (tg[sd][1] @ o if o is not None else PF[f_] - PF["mcp_%s" % sd])
        ex = A.post_hh if post_m is not None and post_m[i] else 0.0
        hb = [(a, b_, min(dm, 0.8 * np.linalg.norm(plan_pos("left", a) - plan_pos("right", b_))) if both else dm + ex) for a, b_, dm in HH]
        hb = [(a, b_, dm) for a, b_, dm in hb if np.linalg.norm(PF[a] - PF[b_]) < dm + 0.10]
        bar_h = [BodySphericalBarrier((a, b_), d_min=dm, gain=2.0, safe_displacement_gain=0.0) for a, b_, dm in hb]
        for _ in range(n_it):
            for k_, bs in enumerate((lambda: bar + bar_h, lambda: bar + [HoldBarrier((a, b_), d_min=dm, gain=2.0, safe_displacement_gain=0.0) for a, b_, dm in hb], lambda: bar, lambda: [])):
                try: v = solve_ik(cfg, tasks, A.dt, solver="quadprog", limits=lim, barriers=bs(), safety_break=False); break
                except Exception: v = np.zeros(m.nv); nfb[min(k_, 2)] += k_ < 3   # if infeasible: penetrating pairs only held → no hand-hand barriers → no barriers
            cfg.integrate_inplace(v, A.dt)
            if np.abs(v).max() * A.dt < A.ik_tol: break
    def solve(k, n_it, outs=(), fix=None, plan=None, base_scale=1.0, base_lock=False, g=True):
        """Solve step k: arms in outs (and the base if base_lock) are fixed to plan (zero velocity); base_scale keeps the base to one step's worth of motion even with more iterations."""
        q = cfg.q.copy(); fixed = [IA[sd] for sd in outs] + ([np.arange(jr, jr + 4)] if base_lock else [])
        for ix in fixed: q[ix] = plan[ix]
        cfg.update(q); vl = VL.copy(); vl[jv:jv + 3] *= 1e-12 if base_lock else base_scale
        for sd in outs: vl[IV[sd]] = 1e-12
        m.velocityLimit[:] = vl
        try: tg = targets(idx[k], outs, fix, g); iterate(idx[k], tg, n_it, g)
        finally: m.velocityLimit[:] = VL
        q = cfg.q.copy()
        for ix in fixed: q[ix] = plan[ix]
        cfg.update(q); return q, tg
    def record(k, tg, outs=()):
        pin.forwardKinematics(m, d2, Q[k]); pin.updateFramePlacements(m, d2)
        for side in SIDES:
            if side in outs: err[side][k] = 0.0; continue
            Tm = d2.oMf[m.getFrameId("mcp_%s" % side)]; Te = d2.oMf[m.getFrameId("arm_%s_link4" % SIDES[side]["s"])]; p_t, R_t, e_h = tg[side]
            err[side][k] = [1e3 * np.linalg.norm(Tm.translation - p_t), np.degrees(np.linalg.norm(pin.log3(R_t.T @ Tm.rotation))), 1e3 * np.linalg.norm(Te.translation - e_h)]; tgt[side][k] = pin.SE3(R_t, p_t - Zc).homogeneous
    hold_x = lambda i: 2 if max(TG[sd][2][i] for sd in SIDES) > 0.5 else 1
    # home and outside-window park poses (initial base, both hands together); arm joints outside the window lie between the two
    fixY = lambda y: {sd: (pin.SE3(hr_pose(sd, y, True)[1], hr_pose(sd, y, True)[0]), hr_pose(sd, y, True)[2]) for sd in SIDES}
    iterate(idx[0], targets(idx[0], fix=fixY(0.0), g=False), A.home_iters, g=False); q_home = cfg.q.copy()
    iterate(idx[0], targets(idx[0], fix=fixY(1.0), g=False), A.home_iters, g=False); q_rest = cfg.q.copy(); cfg.update(q_home.copy())
    pin.forwardKinematics(m, d2, q_home); pin.updateFramePlacements(m, d2); QO = {}; Q[:] = q_home
    PH = {sd: d2.oMf[m.getFrameId("mcp_%s" % sd)].translation.copy() for sd in SIDES}; SHd = {sd: d2.oMf[m.getFrameId("arm_%s_link2" % SIDES[sd]["s"])].translation.copy() for sd in SIDES}
    pin.forwardKinematics(m, d2, q_rest); pin.updateFramePlacements(m, d2); PR = {sd: d2.oMf[m.getFrameId("mcp_%s" % sd)].translation.copy() for sd in SIDES}; YO = {}
    pin.forwardKinematics(m, d2, q_home); pin.updateFramePlacements(m, d2)
    HM = {sd: RIG[sd].mesh_pts(np.clip(np.zeros(20), RIG[sd].lo, RIG[sd].hi))[0] @ d2.oMf[m.getFrameId("mcp_%s" % sd)].rotation.T + PH[sd] - Zc for sd in SIDES}   # home hand mesh (canonical frame)
    for sd in SIDES:   # home ↔ park also at a natural speed (yield in advance): when the working other arm or its product comes close to the home hand
        o = "left" if sd == "right" else "right"; po = np.array([TG[o][0][i] for i in idx]) + Zc; dd = seg_dist(PH[sd][None], SHd[o][None], po)
        dp = np.array([prod[1]((HM[sd] - prod[0][i][:3, 3]) @ prod[0][i][:3, :3]).min() for i in idx]) if prod is not None else np.full(K, 1.0)
        ny = max(1, need_steps(q_rest[IA[sd]] - q_home[IA[sd]], np.zeros(7), np.linalg.norm(PR[sd] - PH[sd]), np.zeros(3), True) // step)
        y_raw = np.maximum(np.clip((A.yield_d1 - dd) / (A.yield_d1 - A.yield_d0), 0, 1), np.clip((A.park_p1 - dp) / (A.park_p1 - A.park_p0), 0, 1))
        YO[sd] = spread(y_raw * (win[o] & ~win[sd]), ny, hold=True)
        QO[sd] = q_home[IA[sd]][None] + YO[sd][:, None] * (q_rest[IA[sd]] - q_home[IA[sd]])[None]; Q[:, IA[sd]] = QO[sd]
    # First pass: human hand targets inside the window; on blend steps before/after the window, home ↔ window-edge hand targets blended in wrist space (lets the base follow early; fallback path when the joint-space blend is blocked); other arms outside the window are fixed
    SOFT = {sd: {} for sd in SIDES}   # step → (window-edge step, window-side weight)
    for sd in SIDES:
        ks = np.nonzero(win[sd])[0]
        if not len(ks): continue
        for kk, into in ((int(ks[0]), True), (int(ks[-1]), False)):
            if kk == (0 if into else K - 1): continue
            T = max(1, need_steps(np.zeros(7), np.zeros(7), np.linalg.norm(hr_pose(sd, 0.0, True)[0] - TG[sd][0][idx[kk]] - Zc), np.zeros(3), True) // step)
            for k in (range(max(0, kk - T), kk) if into else range(kk + 1, min(K, kk + 1 + T))): SOFT[sd][k] = (kk, mj((k - kk + T) / T)[0] if into else 1 - mj((k - kk) / T)[0])
    def soft_fix(sd, k):
        kk, w = SOFT[sd][k]; i = idx[kk]; p0, R0, u0 = hr_pose(sd, YO[sd][k], True); R1 = TG[sd][1][i]
        u1 = tr[sd]["el"][i] - tr[sd]["sh"][i]; u = (1 - w) * u0 + w * u1 / max(np.linalg.norm(u1), 1e-6)
        return pin.SE3(R0 @ pin.exp3(w * pin.log3(R0.T @ R1)), (1 - w) * p0 + w * (TG[sd][0][i] + Zc)), u / np.linalg.norm(u)
    actx = act | np.array([any(k in SOFT[sd] for sd in SIDES) for k in range(K)]); blocks, k = [], 0
    while k < K:
        if actx[k]:
            k1 = k
            while k1 + 1 < K and actx[k1 + 1]: k1 += 1
            blocks.append((k, k1)); k = k1 + 1
        else: k += 1
    prev = None
    for k0, k1 in blocks:
        cfg.update((q_home if prev is None else Q[prev]).copy())
        for k in range(k0, k1 + 1):
            sf = [sd for sd in SIDES if not win[sd][k] and k in SOFT[sd]]; outs = [sd for sd in SIDES if not win[sd][k] and sd not in sf]
            new = any(win[sd][k] and (k == k0 or not (win[sd][k - 1] or k - 1 in SOFT[sd])) for sd in SIDES)   # a hand whose window opens without a blend (first step of the episode)
            q, tg = solve(k, (A.home_iters if new else iters) * hold_x(idx[k]), outs=outs, fix={sd: soft_fix(sd, k) for sd in sf}, plan=Q[k], base_scale=iters / A.home_iters if (new and k > k0) else A.tr_base if sf else 1.0)
            Q[k] = q; record(k, tg, outs + sf)
        prev = k1
    Q1 = Q.copy()
    TR = {sd: dict(s=-1, a=-1, b=-1, e=-1, r_in=1.0, r_out=1.0, m_in="-", m_out="-") for sd in SIDES}; WH = {sd: win[sd].astype(float) for sd in SIDES}
    if not transit or not blocks: return m, Q, err, xy, jr, nfb, TR, tgt, WH
    B3 = lambda q: np.array([q[jr], q[jr + 1], np.arctan2(q[jr + 3], q[jr + 2])]); bh = B3(q_home); bid = m.getFrameId("base_link")
    def bdiff(b1, b0): d_ = b1 - b0; d_[2] = wrap(d_[2]); return d_
    def body(q, f_):
        pin.forwardKinematics(m, d2, q); pin.updateFramePlacements(m, d2); return d2.oMf[bid].inverse() * d2.oMf[m.getFrameId(f_)]
    # 1) Arms: home → window start, window end → home (joint space; base kept from the first pass)
    for sd in SIDES:
        ks = np.nonzero(win[sd])[0]
        if not len(ks): continue
        ka, kb = int(ks[0]), int(ks[-1]); TR[sd].update(a=ka, b=kb)
        if ka > 0:
            k2 = min(ka + 2, kb); v1 = (Q[k2, IA[sd]] - Q[ka, IA[sd]]) / max(k2 - ka, 1)   # joint velocity at window start (per step)
            dq = Q[ka, IA[sd]] - QO[sd][ka]; qa = Q[ka].copy(); qa[IA[sd]] = QO[sd][ka]
            T = need_steps(dq, v1, np.linalg.norm(body(Q[ka], "mcp_%s" % sd).translation - body(qa, "mcp_%s" % sd).translation), np.zeros(3), True); s = max(0, ka - T); L = ka - s
            TR[sd].update(s=s, r_in=T / max(L, 1), m_in="joint"); v1 = end_vel(v1, dq, L); Q[:s, IA[sd]] = QO[sd][:s]
            for k in range(s, ka):
                h5, h4, _ = mj((k - s) / L); Q[k, IA[sd]] = QO[sd][k] + dq * h5 + L * v1 * h4; WH[sd][k] = h5
        if kb < K - 1:
            k2 = max(kb - 2, ka); v0 = (Q[kb, IA[sd]] - Q[k2, IA[sd]]) / max(kb - k2, 1)   # joint velocity at window end
            dq = Q[kb, IA[sd]] - QO[sd][kb]; qb = Q[kb].copy(); qb[IA[sd]] = QO[sd][kb]
            T = need_steps(dq, v0, np.linalg.norm(body(Q[kb], "mcp_%s" % sd).translation - body(qb, "mcp_%s" % sd).translation), np.zeros(3), False); e = min(K - 1, kb + T); L = e - kb
            TR[sd].update(e=e, r_out=T / max(L, 1), m_out="joint"); v0 = end_vel(v0, dq, L); Q[e + 1:, IA[sd]] = QO[sd][e + 1:]
            for k in range(kb + 1, e + 1):
                h5, _, h1 = mj((k - kb) / L); Q[k, IA[sd]] = QO[sd][k] + dq * (1 - h5) + L * v0 * h1; WH[sd][k] = 1 - h5
    # 2) Base: on steps where both hands are outside the window, quintic blends start pose → first window start, between windows, and last window end → start pose (matching window-edge velocity; steps with at least one hand inside a window keep the first pass)
    def bvel(k, back):
        k2 = k - 1 if back else k + 1
        return bdiff(B3(Q[k]), B3(Q[k2])) if back and k2 >= 0 and act[k2] else bdiff(B3(Q[k2]), B3(Q[k])) if not back and k2 < K and act[k2] else np.zeros(3)
    def bfill(k_from, k_to, b0, v0, b1, v1, ks):
        L = max(k_to - k_from, 1); d_ = bdiff(b1, b0); v0, v1 = end_vel(v0, d_, L), end_vel(v1, d_, L)
        for k in ks:
            h5, h4, h1 = mj((k - k_from) / L); b = b0 + d_ * h5 + L * v1 * h4 + L * v0 * h1; Q[k, jr:jr + 4] = [b[0], b[1], np.cos(b[2]), np.sin(b[2])]
    ub, k = [], 0   # blocks where at least one hand is inside a window
    while k < K:
        if act[k]:
            k1 = k
            while k1 + 1 < K and act[k1 + 1]: k1 += 1
            ub.append((k, k1)); k = k1 + 1
        else: k += 1
    bneed = lambda d_: need_steps(np.zeros(7), np.zeros(7), 0.0, d_, True)
    if ub and ub[0][0] > 0:
        k0 = ub[0][0]; s_b = max(0, min([TR[sd]["s"] for sd in SIDES if TR[sd]["a"] == k0 and TR[sd]["s"] >= 0] + [k0 - bneed(bdiff(B3(Q[k0]), bh))]))
        Q[:s_b, jr:jr + 4] = q_home[jr:jr + 4]; bfill(s_b, k0, bh, np.zeros(3), B3(Q[k0]), bvel(k0, False), range(s_b, k0))
    for (_, e1), (s2, _) in zip(ub[:-1], ub[1:]): bfill(e1, s2, B3(Q[e1]), bvel(e1, True), B3(Q[s2]), bvel(s2, False), range(e1 + 1, s2))
    if ub and ub[-1][1] < K - 1:
        k1 = ub[-1][1]; e_b = min(K - 1, max([k1 + bneed(bdiff(bh, B3(Q[k1])))] + [TR[sd]["e"] for sd in SIDES if TR[sd]["b"] == k1]))
        bfill(k1, e_b, B3(Q[k1]), bvel(k1, True), bh, np.zeros(3), range(k1 + 1, e_b + 1)); Q[e_b + 1:, jr:jr + 4] = q_home[jr:jr + 4]
    # 3) During transitions, fingertip spheres follow a home-finger → window-edge-finger blend (for checks)
    for sd in SIDES:
        t_ = TR[sd]; F0 = np.clip(np.zeros(20), RIG[sd].lo, RIG[sd].hi)
        for ks_, kk in ((range(t_["s"], t_["a"]), t_["a"]), (range(t_["b"] + 1, t_["e"] + 1), t_["b"])):
            ks_ = [k for k in ks_ if k >= 0]
            if ks_ and kk >= 0: TIP[sd][[idx[k] for k in ks_]] = RIG[sd].rows(F0[None] + WH[sd][ks_][:, None] * (TG[sd][3][idx[kk]] - F0)[None], tips=True)[1]
    # 4) Path check: if the joint-space blend takes the hand further into the counter, product, other hand or other arm than at its endpoints, push it out; if violations remain, keep whichever of it and the first pass's wrist-space path violates less
    F0H = {sd: np.clip(np.zeros(20), RIG[sd].lo, RIG[sd].hi) for sd in SIDES}
    def mesh(k, sd):
        """Hand mesh points (canonical frame) and mcp pose at step k; during transitions the fingers blend home → window edge."""
        t_ = TR[sd]; kk = t_["a"] if k < t_["a"] else t_["b"]; qf = F0H[sd] + WH[sd][k] * (TG[sd][3][idx[kk]] - F0H[sd]) if kk >= 0 else F0H[sd]
        T_ = d2.oMf[m.getFrameId("mcp_%s" % sd)]; return RIG[sd].mesh_pts(qf)[0] @ T_.rotation.T + T_.translation - Zc, T_
    def clr(k, sd):
        """Min clearances: hand-mesh height above the counter, hand-hand spheres, hand mesh to product surface, hand ↔ other-arm spheres."""
        i = idx[k]; tip_frames(i); pin.forwardKinematics(m, d2, Q[k]); pin.updateFramePlacements(m, d2); P_ = lambda f_: d2.oMf[m.getFrameId(f_)].translation
        X, _ = mesh(k, sd); oc = on_counter(X); cp = float(prod[1]((X - prod[0][i][:3, 3]) @ prod[0][i][:3, :3]).min()) if prod is not None else 1.0
        o = "left" if sd == "right" else "right"; ah = min(np.linalg.norm(P_(a) - P_(b_)) - dm for a, b_, dm in AH[sd] + AH[o])
        return np.array([X[oc, 2].min() if oc.any() else 1.0, min(np.linalg.norm(P_(a) - P_(b_)) - dm for a, b_, dm in HH), cp, ah])
    def thresh(ends, sd):
        E = np.array([clr(k, sd) for k in ends]); return np.r_[min(0.02, E[:, 0].min()) - 0.003, min(A.tr_hh, E[:, 1].min()) - 0.005, min(0.015, E[:, 2].min()) - 0.002, min(0.0, E[:, 3].min()) - 0.005]   # generous product clearance: the product attached to the holding hand can deviate from the product pose in the human data
    def th_at(th, k, ends, key):
        """Return-to-home transition after the last release (product work is done): raise the hand-hand clearance to tr_hh over tr_ramp steps instead of tying it to the start pose."""
        if key != "m_out" or post_m is None or not post_m[idx[ends[0]]] or th[1] >= A.tr_hh: return th
        t_ = th.copy(); t_[1] += (A.tr_hh - th[1]) * min(1.0, (k - ends[0]) / max(A.tr_ramp, 1)); return t_
    def badness(ks, ends, sd, key=None):
        th = thresh(ends, sd); return sum(np.maximum(0.0, th_at(th, k, ends, key) - clr(k, sd)) for k in ks)   # amount below the counter / hand-hand / product / other-arm thresholds (m)
    def push(k, sd, th):
        """Arm joint change (damped least squares) that pushes out, at step k, the hand-mesh points below threshold (up from the counter, out of the product) and the hand spheres (away from the other hand); None if nothing to fix."""
        i = idx[k]; tip_frames(i); pin.computeJointJacobians(m, d2, Q[k]); pin.updateFramePlacements(m, d2); rows, need = [], []
        P_ = lambda f_: d2.oMf[m.getFrameId(f_)].translation; J6 = lambda f_: pin.getFrameJacobian(m, d2, m.getFrameId(f_), pin.ReferenceFrame.LOCAL_WORLD_ALIGNED)[:, IV[sd]]
        X, T_ = mesh(k, sd); Jm = J6("mcp_%s" % sd); Jpt = lambda x: Jm[:3] - pin.skew(x + Zc - T_.translation) @ Jm[3:]
        oc = on_counter(X)
        if oc.any():
            j_ = int(np.argmin(np.where(oc, X[:, 2], np.inf)))
            if X[j_, 2] < th[0]: rows.append(Jpt(X[j_])); need.append(np.array([0.0, 0.0, th[0] - X[j_, 2] + 0.01]))
        if prod is not None:
            To = prod[0][i]; L_ = (X - To[:3, 3]) @ To[:3, :3]; c_ = prod[1](L_); j_ = int(np.argmin(c_))
            if c_[j_] < th[2]: n_ = To[:3, :3] @ prod[1].normal(L_[j_]); rows.append(Jpt(X[j_])); need.append(n_ / max(np.linalg.norm(n_), 1e-9) * (th[2] - c_[j_] + 0.01))
        for a, b_, dm in HH:
            fa, fb = (a, b_) if sd == "left" else (b_, a); d_ = P_(fa) - P_(fb); g_ = np.linalg.norm(d_) - dm
            if g_ < th[1]: rows.append(J6(fa)[:3]); need.append(d_ / max(np.linalg.norm(d_), 1e-9) * (th[1] - g_ + 0.005))
        if not rows: return None
        J = np.vstack(rows); return J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(len(J)), np.concatenate(need))
    def repair(sd, ks, ends, key=None, rounds=8):
        """Push violating steps of a joint-space blend back out: corrections spread smoothly to neighbouring steps; the accumulated correction stays within 0.7 tr_jv joint speed and is 0 at both ends."""
        th = thresh(ends, sd); ix = np.ix_(ks, IA[sd]); Q0 = Q[ix].copy(); C = np.zeros_like(Q0); lo, hi = m.lowerPositionLimit[IA[sd]], m.upperPositionLimit[IA[sd]]
        for _ in range(rounds):
            Dl = [push(k, sd, th_at(th, k, ends, key)) for k in ks]
            if all(d_ is None for d_ in Dl): return
            D = np.array([d_ if d_ is not None else np.zeros(7) for d_ in Dl]); Ds = gaussian_filter1d(D, 2.0, axis=0, mode="constant"); Ds *= np.abs(D).max(0) / np.maximum(np.abs(Ds).max(0), 1e-12)
            C = SM.clamp(np.r_[np.zeros((1, 7)), C + Ds, np.zeros((1, 7))], np.full(7, 0.7 * A.tr_jv), np.full(7, -9.0), np.full(7, 9.0), fps=A.fps)[1:-1]
            C = SM.clamp(np.r_[np.zeros((1, 7)), C, np.zeros((1, 7))], np.full(7, 0.7 * A.tr_jv), np.full(7, -9.0), np.full(7, 9.0), fps=A.fps)[1:-1]   # clamp twice to enforce zero at both ends
            Q[ix] = np.clip(Q0 + C, lo, hi)
    for sd in SIDES:
        t_ = TR[sd]
        for key, ks, ends in (("m_in", list(range(t_["s"], t_["a"])), (t_["s"], t_["a"])), ("m_out", list(range(t_["b"] + 1, t_["e"] + 1)), (t_["b"], t_["e"]))):
            if not ks or min(ends) < 0: continue
            b0 = badness(ks, ends, sd, key)
            if b0.sum() <= 0: continue
            keep0 = Q[np.ix_(ks, IA[sd])].copy(); repair(sd, ks, ends, key); br = badness(ks, ends, sd, key)
            if br.sum() < b0.sum(): b0 = br; t_[key] = "joint+"
            else: Q[np.ix_(ks, IA[sd])] = keep0
            if b0.sum() <= 0: continue
            sk = sorted(set(ks) | {k for k, (kk, _) in SOFT[sd].items() if kk == ends[1 if key == "m_in" else 0]}); ix = np.ix_(sk, IA[sd]); keep = Q[ix].copy(); Q[ix] = Q1[ix]
            b1 = badness(sk, ends, sd, key); why = lambda b: "%s%.0f" % ("chpa"[int(np.argmax(b))], 1e3 * b.max())
            jv1 = np.abs(np.diff(Q[max(sk[0] - 1, 0):sk[-1] + 2][:, IA[sd]], axis=0)).max() * A.fps   # reject the wrist-space path if it spins joints quickly (IK branch switch)
            if b1.sum() < b0.sum() and jv1 <= 2 * A.tr_jv:
                t_[key] = "wrist" if b1.sum() <= 0 else "wrist!" + why(b1)
                for k in sk: WH[sd][k] = SOFT[sd][k][1] if k in SOFT[sd] else float(key == "m_in" and k >= ends[1])
            else: Q[ix] = keep; t_[key] = t_[key] + "!" + why(b0)
    return m, Q, err, xy, jr, nfb, TR, tgt, WH
def mcp_poses(m, Q):
    d2 = m.createData(); out = {sd: [] for sd in SIDES}
    for q in Q:
        pin.forwardKinematics(m, d2, q); pin.updateFramePlacements(m, d2)
        for sd in SIDES: T_ = d2.oMf[m.getFrameId("mcp_%s" % sd)]; out[sd].append(pin.SE3(T_.rotation.copy(), T_.translation - Zc))
    return out
def head_track(Q, m, prim):
    """Per-frame head joints (camera aimed at the primary hand's fingertip)."""
    d = full.createData(); jr_f = full.joints[full.getJointId("root_joint")].idx_q; ih = [full.joints[full.getJointId(n_)].idx_q for n_ in HEAD]; lo, hi = full.lowerPositionLimit[ih], full.upperPositionLimit[ih]
    jr = m.joints[m.getJointId("root_joint")].idx_q; ia_m = [m.joints[m.getJointId(nm)].idx_q for nm in ARM]; ia_f = [full.joints[full.getJointId(nm)].idx_q for nm in ARM]
    H = np.zeros((len(Q), 2)); err = np.zeros(len(Q)); h = np.clip(np.zeros(2), lo, hi)
    for t, q in enumerate(Q):
        qf = pin.neutral(full); qf[jr_f:jr_f + 4] = q[jr:jr + 4]; qf[ia_f] = q[ia_m]; tip = "finger_end_%s_link3" % prim[t][0]
        def res(x):
            qf[ih] = x; pin.forwardKinematics(full, d, qf); pin.updateFramePlacements(full, d); C = d.oMf[full.getFrameId(CAM)]
            u = d.oMf[full.getFrameId(tip)].translation - C.translation; return np.cross(C.rotation[:, 0], u / max(np.linalg.norm(u), 1e-6))
        r = least_squares(res, h, bounds=(lo, hi), max_nfev=30); h = r.x; H[t] = h; err[t] = np.degrees(np.arcsin(min(1.0, np.linalg.norm(r.fun))))
    vmax = 2.0 / A.fps
    for t in range(1, len(H)): H[t] = H[t - 1] + np.clip(H[t] - H[t - 1], -vmax, vmax)
    if len(H) >= 9: H = np.clip(savgol_filter(H, 9, 2, axis=0), lo, hi)
    return H, err
def primary_hand(jid, f0, n):
    segs = sorted([(int(h["start"]), int(h["end_excl"]), h["hand"]) for h in S3[jid]["holding_segments"]]); out = []
    for f in range(f0, f0 + n):
        on = [x for x in segs if x[0] <= f < x[1]]
        if on: out.append(max(on)[2]); continue
        nxt = [x for x in segs if x[0] > f]; out.append(nxt[0][2] if (nxt and f < segs[0][0]) else max(segs, key=lambda x: x[1])[2] if segs else "right")
    return out

# Time map (slow down where the arm cannot keep up)
def rs_lin(X, TM):
    X = np.asarray(X, float); l = np.clip(np.floor(TM).astype(int), 0, len(X) - 1); h = np.clip(l + 1, 0, len(X) - 1); a = (TM - l).reshape((-1,) + (1,) * (X.ndim - 1)); return (1 - a) * X[l] + a * X[h]
def rs_R(R, TM):
    l = np.clip(np.floor(TM).astype(int), 0, len(R) - 1); h = np.clip(l + 1, 0, len(R) - 1); a = TM - l
    return np.array([R[l_] @ pin.exp3(a_ * pin.log3(R[l_].T @ R[h_])) for l_, h_, a_ in zip(l, h, a)])
def retime(TM, n0, err, s_prev, e_prev=None, free=None):
    """Slow down source frames with large errors. A frame already slowed whose error did not drop (unreachable rather than too fast) is not slowed further. Returns (time map, slow-down factors, per-frame error)."""
    s = s_prev.copy(); src = np.clip(np.floor(TM).astype(int), 0, n0 - 1); E = np.zeros(n0); np.maximum.at(E, src, err)
    for f in np.nonzero(E > A.rt_tol)[0]:
        if e_prev is not None and s_prev[f] > 1.0 and E[f] > A.rt_gain * e_prev[f]: continue
        s[f] = max(s[f], s_prev[f] * min(A.rt_step, 1.0 + (E[f] - A.rt_tol) / A.rt_k))
    s = np.clip(gaussian_filter1d(maximum_filter1d(s, 5), 1.5), 1.0, np.where(free, A.rt_max_free, A.rt_max) if free is not None else A.rt_max); t, out = 0.0, []
    while t <= n0 - 1 + 1e-9: out.append(t); t += 1.0 / s[min(int(t), n0 - 1)]
    if out[-1] < n0 - 1: out.append(float(n0 - 1))
    return np.array(out), s, E

def tip_err(side, R, p, Q, tip):
    """Fingertip error (mm), (n,5)."""
    C, _ = RIG[side].chain_pts(Q); return 1e3 * np.linalg.norm(np.einsum("bij,bfj->bfi", R, C[:, :, 3]) + p[:, None] - tip, axis=-1)

OUT_IK, OUT_H = {}, {}; t_start = time.time(); NEP = 0
def episode(jid):
    t_ep = time.time(); c = CL.get(jid)
    if c is None or jid not in S3: return
    f0, n = int(c["session_frame0"]), int(c["n"])
    if f0 + n > len(TRI): return
    tr = human_arms(f0, n); X = {sd: human_hand(sd, f0, n) for sd in SIDES}
    if tr is None or any(v is None for v in X.values()): print(jid, "skip: keypoints missing", flush=True); return
    obj = load_obj(jid, f0, n)
    segs = {sd: sorted((int(h["start"]) - f0, int(h["end_excl"]) - f0) for h in S3[jid]["holding_segments"] if h["hand"] == sd) for sd in SIDES}
    segs = {sd: [(max(a, 0), min(b, n)) for a, b in v if min(b, n) > max(a, 0)] for sd, v in segs.items()}
    smid = 0.5 * (tr["left"]["sh"] + tr["right"]["sh"]); fwd_ = np.cross(tr["left"]["sh"] - tr["right"]["sh"], [0, 0, 1.0]); yaw = float(np.arctan2(np.median(fwd_[:, 1]), np.median(fwd_[:, 0])))
    fwd = np.array([np.cos(yaw), np.sin(yaw), 0.0]); xy0 = np.median(smid[:, :2], 0); x_edge = counter_box()["x0"] - A.robot_clear; WIN0 = windows(segs, n); POST0 = np.arange(n) >= max((b for v in segs.values() for _, b in v), default=n); g_ep = min(a for v in segs.values() for a, _ in v) if any(segs.values()) else n
    # 1. Hands: per-frame hand frame and fingers fitted to the human hand inside the window (plan); 2. wrist shift. Fingers outside the window are at home (zero)
    PL = {}
    for sd in SIDES:
        tip, U, Rp = HR.human_targets(X[sd], RIG[sd].B); win = WIN0[sd]; R, p, q = np.tile(np.eye(3), (n, 1, 1)), X[sd][:, [5, 9, 13, 17]].mean(1), np.zeros((n, 20))
        off, t0_, t1_, e_plan = np.zeros((n, 3)), 0, 0, np.zeros((1, 5))
        if win.any():
            ks = np.nonzero(win)[0]; r0, r1 = max(0, ks[0] - A.track_warm), ks[-1] + 1
            R_, p_, q_, _ = RIG[sd].track(tip[r0:r1], U[r0:r1], Rp[r0:r1], vmax=A.fq_vmax); R[r0:r1], p[r0:r1], q[r0:r1] = R_, p_, q_
            R[:r0], p[:r0], R[r1:], p[r1:] = R_[0], p_[0], R_[-1], p_[-1]; e_plan = tip_err(sd, R_, p_, q_, tip[r0:r1])[ks[0] - r0:]
            off, t0_, t1_ = shift(sd, p, R, q, obj, g_ep, segs[sd][-1][1] if segs[sd] else n, fwd, win)   # from the episode's first grasp both hands may touch the product
        PL[sd] = dict(R=R, p=p, q=q, tip=tip, U=U, off=off, wg=interact_w(segs[sd], n), touch0=t0_, touch=t1_, e_plan=e_plan)
    for sd in SIDES: PL[sd]["y"], PL[sd]["free"] = yield_w(sd, PL, tr, segs, n, WIN0)   # 3. idle hands move toward the rest pose when close to the working hand/arm
    TG0 = {sd: (PL[sd]["p"] + PL[sd]["off"], PL[sd]["R"], PL[sd]["wg"], PL[sd]["q"], PL[sd]["y"], PL[sd]["free"].astype(float)) for sd in SIDES}
    best = None
    for dx in A.dx_grid:   # grid over the base back-off distance
        e_ = ik_solve(TG0, tr, WIN0, yaw, xy0, x_edge, dx, step=6, iters=20, prod=obj, transit=False, post_m=POST0)[2]; E = np.concatenate([e_[s][WIN0[s][::6]] for s in SIDES])
        c_ = np.percentile(E[:, 0], 90) + 2.0 * np.percentile(E[:, 1], 90) + 0.2 * np.median(E[:, 2])
        if best is None or c_ < best[0]: best = (c_, dx)
    dx = best[1]
    def arm_final(m, Q, err, TGT, WIN):
        """Final arm joints after velocity-limit smoothing, plus the resulting hand frames and errors (holding frames keep the raw IK solution, without smoothing)."""
        Q, err = Q.copy(), {k: e.copy() for k, e in err.items()}; ia = [m.joints[m.getJointId(nm)].idx_q for nm in ARM]; iv = [m.joints[m.getJointId(nm)].idx_v for nm in ARM]
        Qs_ = SM.joints(Q[:, ia], m.velocityLimit[iv], m.lowerPositionLimit[ia], m.upperPositionLimit[ia])
        for side in SIDES:
            g_ = TG[side][2][:, None]; k_ = [ia.index(m.joints[m.getJointId("arm_%s_joint%d" % (SIDES[side]["s"], j))].idx_q) for j in range(1, 8)]
            Qs_[:, k_] = (1 - g_) * Qs_[:, k_] + g_ * Q[:, ia][:, k_]
        Q[:, ia] = SM.clamp(Qs_, m.velocityLimit[iv], m.lowerPositionLimit[ia], m.upperPositionLimit[ia]); HT = mcp_poses(m, Q)
        for side in SIDES:   # errors are measured against the targets IK actually used (blended with home/rest poses)
            for t in np.nonzero(WIN[side] & np.isfinite(TGT[side][:, 0, 0]))[0]: err[side][t, :2] = [1e3 * np.linalg.norm(HT[side][t].translation - TGT[side][t][:3, 3]), np.degrees(np.linalg.norm(pin.log3(TGT[side][t][:3, :3].T @ HT[side][t].rotation)))]
        return Q, HT, err
    TC = np.arange(n, dtype=float); s_ = np.ones(n); e_prev = None; FREE0 = ~(WIN0["left"] | WIN0["right"])
    P0 = 0 if any(v and v[0][0] == 0 for v in segs.values()) else A.edge_pad   # a clip that starts mid-grasp cannot start from home
    P1 = 0 if any(v and v[-1][1] >= n for v in segs.values()) else A.edge_pad
    for rt in range(A.retime_rounds + 1):
        TM = np.r_[np.zeros(P0), TC, np.full(P1, n - 1.0)]; core = np.r_[np.zeros(P0, bool), np.ones(len(TC), bool), np.zeros(P1, bool)]
        TG = {sd: (rs_lin(TG0[sd][0], TM), rs_R(TG0[sd][1], TM)) + tuple(rs_lin(x, TM) for x in TG0[sd][2:]) for sd in SIDES}
        trT = {sd: dict(sh=rs_lin(tr[sd]["sh"], TM), el=rs_lin(tr[sd]["el"], TM)) for sd in SIDES}; WINT = {sd: (rs_lin(WIN0[sd].astype(float), TM) >= 1 - 1e-9) & core for sd in SIDES}
        obT = None if obj is None else (np.concatenate([np.concatenate([rs_R(obj[0][:, :3, :3], TM), rs_lin(obj[0][:, :3, 3], TM)[:, :, None]], 2), np.tile([[[0, 0, 0, 1.0]]], (len(TM), 1, 1))], 1), obj[1])
        m, Q, err, xy, jr, fb, TR, TGT, WH = ik_solve(TG, trT, WINT, yaw, xy0, x_edge, dx, prod=obT, post_m=rs_lin(POST0.astype(float), TM) >= 0.5)
        ia_, iv_ = [m.joints[m.getJointId(nm)].idx_q for nm in ARM], [m.joints[m.getJointId(nm)].idx_v for nm in ARM]; vr = np.r_[0.0, (np.abs(np.diff(Q[:, ia_], axis=0)) / (m.velocityLimit[iv_] / A.fps)).max(1)]
        Q, HT, err = arm_final(m, Q, err, TGT, WINT)   # retiming is driven by the smoothed final arm's error (against the targets actually used)
        e_ = np.maximum(err["left"][:, 0] * WINT["left"], err["right"][:, 0] * WINT["right"])
        ov_ = maximum_filter1d((np.convolve(vr > 1.0, np.ones(3), "same") >= 3).astype(float), 3) > 0   # spans where the IK joint speed exceeds the limit for 3+ consecutive steps (isolated spikes are left to smoothing)
        e_ = np.maximum(e_, np.where(ov_ & (vr > 1.0), A.rt_tol + A.rt_k * (vr - 1.0) + 1e-6, 0.0))   # slow those spans down in proportion to the excess
        for t_ in TR.values():   # if a home ↔ window transition was squeezed into too little time, stretch that span by the shortfall ratio
            if t_["r_in"] > 1.05: e_[:t_["a"]] = np.maximum(e_[:t_["a"]], A.rt_tol + A.rt_k * (t_["r_in"] - 1.0) + 1e-6)
            if t_["r_out"] > 1.05: e_[t_["b"] + 1:] = np.maximum(e_[t_["b"] + 1:], A.rt_tol + A.rt_k * (t_["r_out"] - 1.0) + 1e-6)
        e_ = e_ * core; bad = int((e_ > A.rt_tol).sum())
        if bad == 0 or rt == A.retime_rounds: break
        TC, s_, e_prev = retime(TC, n, e_[core], s_, e_prev if rt else None, FREE0); print("%s retime round %d: %d steps over %.0f mm → %d steps (x%.2f)" % (jid, rt + 1, bad, A.rt_tol, len(TC), len(TC) / n), flush=True)
    nT = len(TM); SRCI = np.clip(np.rint(TM), 0, n - 1).astype(int); ia = [m.joints[m.getJointId(nm)].idx_q for nm in ARM]
    k0, k1 = active_span(Q[:, ia + list(range(jr, jr + 4))]); ct = slice(k0, k1 + 1)   # drop idle steps before leaving home and after returning home
    # 4. Fingers from the final wrist: inside the window, re-fit to the human fingertips (+ wrist shift) carried by the IK target hand frame (moved toward the reached hand frame by the rest-pose weight); outside the window home (zero); during transitions blended like the arm
    stat = {}
    for side in SIDES:
        Ra = np.array([T_.rotation for T_ in HT[side]]); pa = np.array([T_.translation for T_ in HT[side]]); t_ = TR[side]; F0 = np.clip(np.zeros(20), RIG[side].lo, RIG[side].hi); Fq = np.tile(F0, (nT, 1)); e_fin = np.zeros((1, 5))
        if t_["a"] >= 0:
            sl = slice(t_["a"], t_["b"] + 1); Rt, pt = TG[side][1][sl], TG[side][0][sl]
            tipT = rs_lin(PL[side]["tip"] + PL[side]["off"][:, None], TM)[sl]; UT = rs_lin(PL[side]["U"], TM)[sl]; UT /= np.linalg.norm(UT, axis=-1, keepdims=True)
            wr = 1 - TG[side][4][sl]; Rr = np.array([R_a @ pin.exp3(w_ * pin.log3(R_a.T @ R_t)) for R_a, R_t, w_ in zip(Ra[sl], Rt, wr)]); pr = (1 - wr)[:, None] * pa[sl] + wr[:, None] * pt
            M = Rr @ np.swapaxes(Rt, -1, -2); tipB = np.einsum("bij,bfj->bfi", M, tipT - pt[:, None]) + pr[:, None]; UB = np.einsum("bij,bfkj->bfki", M, UT)
            _, _, Fw, _ = RIG[side].track(tipB, UB, pose=(Ra[sl], pa[sl]), q_init=TG[side][3][sl], vmax=A.fq_vmax); Fq[sl] = Fw
            for k in range(max(t_["s"], 0), t_["a"]): Fq[k] = F0 + WH[side][k] * (Fw[0] - F0)
            for k in range(t_["b"] + 1, t_["e"] + 1): Fq[k] = F0 + WH[side][k] * (Fw[-1] - F0)
            full_ = TG[side][4][sl] <= 0; e_fin = tip_err(side, Ra[sl], pa[sl], Fw, tipB)[full_]
        OUT_H["%s|%s__fingers" % (jid, side)] = Fq[ct].astype(np.float32)
        OUT_IK["%s|%s__err" % (jid, side)] = err[side][ct].astype(np.float32); OUT_IK["%s|%s__avoid" % (jid, side)] = rs_lin(PL[side]["off"], TM)[ct].astype(np.float32)
        OUT_IK["%s|%s__hand_T" % (jid, side)] = np.array([T_.homogeneous for T_ in HT[side]], np.float32)[ct]
        OUT_IK["%s|%s__target_T" % (jid, side)] = np.where(np.isfinite(TGT[side][ct, :1, :1]), TGT[side][ct], OUT_IK["%s|%s__hand_T" % (jid, side)]).astype(np.float32)   # outside the window: the reached hand pose
        OUT_IK["%s|%s__yield" % (jid, side)] = TG[side][4][ct].astype(np.float32); OUT_IK["%s|%s__w" % (jid, side)] = WH[side][ct].astype(np.float32)   # human weight: 1 inside the window, 0 at home, in between during transitions
        OUT_IK["%s|%s__win" % (jid, side)] = np.array([-1 if t_[k] < 0 else min(max(t_[k] - k0, 0), k1 - k0) for k in "sabe"])   # steps: transition start, window start, window end, transition end (-1 = none)
        stat[side] = dict(plan=np.median(PL[side]["e_plan"], 0), fin=np.median(e_fin, 0) if len(e_fin) else np.zeros(5), self=1e3 * max(RIG[side].self_max(q) for q in Fq[::4]))
    OUT_H["%s|finger_joint_names" % jid] = np.array(["finger_l_joint%d" % j for j in range(1, 21)])
    btr = np.stack([Q[:, jr], Q[:, jr + 1], np.unwrap(np.arctan2(Q[:, jr + 3], Q[:, jr + 2])), np.zeros(nT)], 1)
    prim = primary_hand(jid, f0, n); HQ, gerr = head_track(Q, m, [prim[k] for k in SRCI])
    gk = ["%s|%s|%d|G" % (jid, sd, a + f0) for sd in SIDES for a, b in segs[sd]]
    OUT_IK.update({jid + "|q": Q[ct][:, ia].astype(np.float32), jid + "|joint_names": np.array(ARM), jid + "|base_traj": btr[ct].astype(np.float32), jid + "|head": HQ[ct].astype(np.float32),
                   jid + "|base": np.array([xy[0], xy[1], -A.counter_h, yaw, 0.0, dx]), jid + "|frames": f0 + SRCI[ct], jid + "|tmap": (f0 + TM[ct]).astype(np.float64), jid + "|w": np.maximum(WH["left"], WH["right"])[ct].astype(np.float32), jid + "|grasp_ok": np.array(gk or [""])})
    Qa = Q[:, ia]; lo, hi = m.lowerPositionLimit[ia], m.upperPositionLimit[ia]; near = float(np.mean((Qa - lo < 0.05) | (hi - Qa < 0.05))); jump = np.degrees(np.abs(np.diff(Qa, axis=0)).max(1))
    E = np.concatenate([err[s][WINT[s]] for s in SIDES]); bmove = np.linalg.norm(btr[:, :2] - xy, axis=1)
    tips = lambda v: "/".join("%.0f" % x for x in v)
    trs = lambda t_: "-" if t_["a"] < 0 else "in %d st x%.2f %s, out %d st x%.2f %s" % (t_["a"] - t_["s"] if t_["s"] >= 0 else 0, t_["r_in"], t_["m_in"], t_["e"] - t_["b"] if t_["e"] >= 0 else 0, t_["r_out"], t_["m_out"])
    print("%s n %d cut %d+%d lift %.3f back %.2f yaw %.0f° | hand pos p50 %.1f p90 %.1f mm, rot p50 %.1f p90 %.1f°, elbow dir p50 %.0f mm, near-limit %.1f%%, joint step p95 %.1f max %.0f° | base move max %.0f mm, yaw %.0f° | tip err mm plan L %s R %s final L %s R %s, self max L %.1f R %.1f mm | shift touching frames L %d→%d R %d→%d, max offset L %.0f R %.0f mm, yield frames L %d R %d | gaze p50 %.0f° | qp barrier fallback %d/%d/%d | transit L %s R %s | %.1f min" % (
        jid, k1 - k0 + 1, k0, nT - 1 - k1, 0.0, dx, np.degrees(yaw), np.median(E[:, 0]), np.percentile(E[:, 0], 90), np.median(E[:, 1]), np.percentile(E[:, 1], 90), np.median(E[:, 2]), 100 * near, np.percentile(jump, 95), jump.max(),
        1e3 * bmove.max(), np.degrees(np.abs(btr[:, 2] - yaw).max()), tips(stat["left"]["plan"]), tips(stat["right"]["plan"]), tips(stat["left"]["fin"]), tips(stat["right"]["fin"]), stat["left"]["self"], stat["right"]["self"],
        PL["left"]["touch0"], PL["left"]["touch"], PL["right"]["touch0"], PL["right"]["touch"], 1e3 * np.linalg.norm(PL["left"]["off"], axis=1).max(), 1e3 * np.linalg.norm(PL["right"]["off"], axis=1).max(), int((PL["left"]["y"] > 0).sum()), int((PL["right"]["y"] > 0).sum()),
        np.median(gerr), *fb, trs(TR["left"]), trs(TR["right"]), (time.time() - t_ep) / 60), flush=True)
    global NEP; NEP += 1

def claim(jid):
    if not A.claim_dir: return True
    try: os.close(os.open(os.path.join(A.claim_dir, jid), os.O_CREAT | os.O_EXCL | os.O_WRONLY)); return True
    except FileExistsError: return False

def main():
    for jid in (A.jids.split(",") if A.jids else sorted(S3)):
        if claim(jid): episode(jid)
    np.savez_compressed(A.out_ik + ".npz", **OUT_IK); np.savez_compressed(A.out_hand + ".npz", **OUT_H)
    info = SRC.ds.info
    json.dump(dict(kind="ARCADE FFW-SH5 retargeting (hand retarget + Pink IK)", counter=counter_box(), counter_h=A.counter_h,
                   release=dict(name=info.get("name"), version=info.get("release_version"), session=info.get("session")),
                   urdf=os.path.basename(A.urdf), args={k: v for k, v in vars(A).items() if k not in ("release", "urdf", "mesh_root", "claim_dir", "out_ik", "out_hand")},
                   mobile_base=True, barriers=dict(torso=TORSO, front=FRONT, hand_r=HAND_R), episodes=NEP, minutes=round((time.time() - t_start) / 60, 1)), open(A.out_ik + ".json", "w"), indent=1)
    json.dump(dict(kind="ARCADE FFW-SH5 finger trajectories (HX5-D20)", ik=os.path.basename(A.out_ik) + ".npz", episodes=NEP), open(A.out_hand + ".json", "w"), indent=1)
    print("RETARGET_DONE %d episodes %.1f min -> %s" % (NEP, (time.time() - t_start) / 60, A.out_ik), flush=True)
if __name__ == "__main__": main()
