"""Rule that attaches a held product to the robot hand for the product export: on held steps the input product pose is
carried from the planned hand frame (fitted to the human hand) to the robot's actual hand frame (the robot hand keeps the
human hand–product relation and moves with the IK error, so the product never floats off the hand). Grasp onsets and
changes of carrying hand are blended over settle_n steps; after release the product settles from the release pose onto
the nearest stable face; before the first grasp the input product track is kept unchanged."""
import numpy as np
from scipy.spatial.transform import Rotation as _R, Slerp


def mix_T(A_, B_, a):
    """Interpolate between two 4×4 poses: linear in position, geodesic in rotation."""
    M = np.eye(4); M[:3, :3] = Slerp([0, 1], _R.from_matrix([A_[:3, :3], B_[:3, :3]]))([a]).as_matrix()[0]; M[:3, 3] = (1 - a) * A_[:3, 3] + a * B_[:3, 3]; return M


def rot_to(u, v):
    """Minimal rotation taking unit vector u to v."""
    c = np.cross(u, v); s_, c_ = np.linalg.norm(c), float(u @ v)
    if s_ < 1e-9:
        if c_ > 0: return np.eye(3)
        k = np.cross(u, [1.0, 0, 0] if abs(u[0]) < 0.9 else [0, 1.0, 0]); k /= np.linalg.norm(k); return 2 * np.outer(k, k) - np.eye(3)   # opposite directions: 180° about a perpendicular axis
    k = c / s_; K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]]); a = np.arctan2(s_, c_); return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K
def bottom(R, dm):
    """Height from the product centre down to its lowest point."""
    if dm["shape"] == "box": return float(np.abs(R[2]) @ (np.array([dm["l"], dm["w"], dm["h"]]) / 2))
    cz = abs(R[2, 2]); return cz * dm["h"] / 2 + np.sqrt(max(0.0, 1 - cz * cz)) * dm["r"]
def settle(T, dm, z_floor):
    """Settle from the release pose onto the nearest stable face (x, y kept; z_floor = support height measured from the input product track)."""
    R = T[:3, :3]
    if dm["shape"] == "box": k = int(np.argmax(np.abs(R[2]))); v = R[:, k] * np.sign(R[2, k]); Rn = rot_to(v, np.array([0, 0, 1.0])) @ R
    elif abs(R[2, 2]) > np.cos(np.radians(45)): v = R[:, 2] * np.sign(R[2, 2]); Rn = rot_to(v, np.array([0, 0, 1.0])) @ R
    else: v = R[:, 2]; h = np.array([v[0], v[1], 0.0]); Rn = rot_to(v, h / max(np.linalg.norm(h), 1e-9)) @ R
    S = np.eye(4); S[:3, :3] = Rn; S[:3, 3] = [T[0, 3], T[1, 3], z_floor + bottom(Rn, dm)]; return S
def ease(t, t0, k): return 0.5 - 0.5 * np.cos(np.pi * min(1.0, (t - t0 + 1) / k))
def attach(T, hold, HT, HG, dm, settle_n=5):
    """T = input product poses (n,4,4), HT, HG = per-hand actual and planned hand frames (n,4,4). On held steps the carrying hand (the one that grasped first) holds the product. Returns (product trajectory, carrying hand: −1 none / 0 left / 1 right)."""
    n = len(T); out = T.copy(); car = np.full(n, -1, int)
    for t in range(n):
        a = [h for h in hold if h["start"] <= t < h["end"]]
        if a: car[t] = ("left", "right").index(min(a, key=lambda h: (h["start"], -h["end"]))["hand"])
    rest = np.array([car[t] < 0 and not any(h["start"] <= t for h in hold) for t in range(n)])   # before the first grasp
    zb = [T[t, 2, 3] - bottom(T[t, :3, :3], dm) for t in range(n) if car[t] < 0]; z_floor = float(np.median(zb)) if zb else 0.0
    carry = lambda c, t: HT[("left", "right")[c]][t].astype(float) @ np.linalg.inv(HG[("left", "right")[c]][t].astype(float)) @ T[t]
    S = None; t_sw = None; prev = None
    for t in range(n):
        c = car[t]
        if c >= 0:
            if t == 0 or c != car[t - 1]: t_sw, prev = t, (car[t - 1] if t > 0 else -1)   # grasp onset or change of carrying hand
            A_ = carry(c, t)
            if t - t_sw < settle_n: A_ = mix_T(carry(prev, t) if prev >= 0 else out[t_sw - 1] if t_sw > 0 else T[t], A_, ease(t, t_sw, settle_n))   # blend from the resting pose (or the previous hand)
            out[t] = A_; S = None
        elif not rest[t]:
            if S is None: S = settle(out[t - 1], dm, z_floor); P0 = out[t - 1].copy(); t_rel = t
            out[t] = mix_T(P0, S, ease(t, t_rel, settle_n))
    return out, car
