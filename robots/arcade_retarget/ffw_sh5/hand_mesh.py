"""Collision-mesh geometry of the HX5-D20 robot hand, read from the URDF link meshes: evenly spaced surface samples
and normals per link, finger pads (flexion-side face of each distal segment), finger-link capsules (self-collision
candidate filtering) and local per-link SDFs (self-collision distances)."""
import hashlib, os
import xml.etree.ElementTree as ET
import numpy as np, pinocchio as pin
from arcade_retarget.ffw_sh5 import urdf_mesh as UM, product_mesh as prodmesh

FINGERS = ("thumb", "index", "middle", "ring", "little")
LINKS = {f: [4 * k + j for j in (1, 2, 3, 4)] for k, f in enumerate(FINGERS)}   # link indices 1..20 per finger; distal segment = last


def link_tris(urdf, mesh_root, names):
    """URDF collision meshes as {link name: (vertices (3m, 3) in link coordinates, faces (m, 3))}."""
    out = {}
    for l in ET.parse(urdf).getroot().iter("link"):
        if l.get("name") not in names: continue
        Vs = []
        for c in l.iter("collision"):
            g = c.find("geometry")[0]; o = c.find("origin")
            if g.tag != "mesh": continue
            fp = g.get("filename").replace("package://", mesh_root)
            if not os.path.exists(fp): continue
            V = UM.stl(fp) * np.array([float(x) for x in g.get("scale", "1 1 1").split()])
            if o is not None: V = V @ pin.utils.rpyToMatrix(*[float(x) for x in o.get("rpy", "0 0 0").split()]).T + np.array([float(x) for x in o.get("xyz", "0 0 0").split()])
            Vs.append(V)
        if Vs: V = np.concatenate(Vs); out[l.get("name")] = (V, np.arange(len(V)).reshape(-1, 3))
    return out


def fps(P, k):
    """Indices of k farthest-point samples (starting from the point farthest from the centroid)."""
    i0 = int(np.argmax(np.linalg.norm(P - P.mean(0), axis=1))); idx = [i0]; d = np.linalg.norm(P - P[i0], axis=1)
    for _ in range(min(k, len(P)) - 1): i = int(np.argmax(d)); idx.append(i); d = np.minimum(d, np.linalg.norm(P - P[i], axis=1))
    return np.array(idx)


def samples(V, F, spacing, kmin=24, kmax=2000):
    """Evenly spaced surface points (spacing in m) and outward normals."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]; area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum()
    k = int(np.clip(area / spacing ** 2, kmin, kmax)); S, N = prodmesh.surface_samples(V, F, 30 * k); i = fps(S, k); return S[i], N[i]


def capsule(P):
    """Capsule enclosing all points (segment end points, radius), used to filter self-collision candidates."""
    c = P.mean(0); u = np.linalg.svd(P - c, full_matrices=False)[2][0]; t = (P - c) @ u; r = float(np.linalg.norm(P - c - np.outer(t, u), axis=1).max())
    t0, t1 = t.min() + r, t.max() - r
    if t1 < t0: t0 = t1 = 0.5 * (t.min() + t.max())
    return np.array([c + t0 * u, c + t1 * u]), r


def seg_dist(P0, P1, Q0, Q1):
    """Shortest distance between segment pairs (broadcast, (..., 3))."""
    d1, d2, r = P1 - P0, Q1 - Q0, P0 - Q0; a = (d1 * d1).sum(-1); e = (d2 * d2).sum(-1); f = (d2 * r).sum(-1); c = (d1 * r).sum(-1); b = (d1 * d2).sum(-1)
    den = np.maximum(a * e - b * b, 1e-12); s = np.clip((b * f - c * e) / den, 0, 1); s = np.where(a * e - b * b < 1e-12, 0.0, s)
    t = (b * s + f) / np.maximum(e, 1e-12); s = np.where(t < 0, np.clip(-c / np.maximum(a, 1e-12), 0, 1), np.where(t > 1, np.clip((b - c) / np.maximum(a, 1e-12), 0, 1), s)); t = np.clip(t, 0, 1)
    return np.linalg.norm(P0 + d1 * s[..., None] - Q0 - d2 * t[..., None], axis=-1)


def pt_seg_dist(X, Q0, Q1):
    """Distance between points (..., 3) and segments (..., 3)."""
    d = Q1 - Q0; t = np.clip(((X - Q0) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-12), 0, 1); return np.linalg.norm(X - Q0 - d * t[..., None], axis=-1)


class Hand:
    """Link samples (link coordinates), pads, capsules and pair list of one hand. names[0] = base, names[k] = finger_<s>_link<k>."""
    def __init__(self, model, urdf, mesh_root, side, spacing=0.004, base_spacing=0.006, self_k=60):
        s = side[0]; self.names = ["hx5_d20_%s_base" % side] + ["finger_%s_link%d" % (s, i) for i in range(1, 21)]
        T = link_tris(urdf, mesh_root, self.names); self.tris = T
        self.P, self.N = [], []
        for k, nm in enumerate(self.names):
            V, F = T[nm]; S, Nn = samples(V, F, base_spacing if k == 0 else spacing, kmin=60 if k == 0 else 24); self.P.append(S); self.N.append(Nn)
        self.lab = np.concatenate([np.full(len(P), k) for k, P in enumerate(self.P)]); self.Pall = np.concatenate(self.P); self.Nall = np.concatenate(self.N)
        self.cap = [capsule(self.P[k]) for k in range(21)]; dense = set(LINKS["thumb"]) | {LINKS[f][-1] for f in FINGERS}
        self.Ps = [P[fps(P, 2 * self_k if k in dense else self_k)] for k, P in enumerate(self.P)]   # denser on the thumb and distal segments (contact areas)
        d = model.createData(); q = pin.neutral(model); fid = [model.getFrameId(n) for n in self.names]
        tipf = [model.getFrameId("finger_end_%s_link%d" % (s, i)) for i in range(1, 6)]; self.palmar = {}
        for fi, f in enumerate(FINGERS):   # flexion side of the distal segment = direction the fingertip moves when the last joint flexes (distal-link coordinates)
            j = model.getJointId("finger_%s_joint%d" % (s, LINKS[f][-1])); iq = model.joints[j].idx_q
            pin.framesForwardKinematics(model, d, q); R0 = d.oMf[fid[LINKS[f][-1]]].rotation.copy(); p0 = d.oMf[tipf[fi]].translation.copy()
            q2 = q.copy(); q2[iq] += 0.1; pin.framesForwardKinematics(model, d, q2); v = R0.T @ (d.oMf[tipf[fi]].translation - p0); self.palmar[f] = v / np.linalg.norm(v)
        self.pad = {f: np.nonzero(self.N[LINKS[f][-1]] @ self.palmar[f] > 0.3)[0] for f in FINGERS}   # distal-segment samples on the pad face
        self.pairs = self._pairs(model, fid)

    def _pairs(self, model, fid):
        """Link pairs across different fingers and finger–base pairs, excluding pairs already in contact in the open (neutral) pose (root housings)."""
        d = model.createData(); pin.framesForwardKinematics(model, d, pin.neutral(model)); out = []
        fing = {k: fi for fi, f in enumerate(FINGERS) for k in LINKS[f]}
        for a in range(0, 21):
            for b in range(a + 1, 21):
                if a and fing[a] == fing[b]: continue
                if a == 0 and b in [LINKS[f][0] for f in FINGERS]: continue
                Pa = self.P[a] @ d.oMf[fid[a]].rotation.T + d.oMf[fid[a]].translation; Pb = self.P[b] @ d.oMf[fid[b]].rotation.T + d.oMf[fid[b]].translation
                if np.min(np.linalg.norm(Pa[:, None] - Pb[None], axis=-1)) > 0.004: out.append((a, b))
        return out

    def link_fields(self, key=None):
        return link_fields(self.names, self.tris)


def link_fields(names, tris):
    """Local link SDFs (1 mm grid for fingers, 1.5 mm for the base) and the grid index per link (identical meshes share one grid). names[0] = base."""
    F_, ids, seen = [], [], {}
    for k, nm in enumerate(names):
        V, F = tris[nm]; h = hashlib.md5(np.round(V, 6).tobytes()).hexdigest()
        if h not in seen:
            res = 0.0015 if k == 0 else 0.001; seen[h] = len(F_)
            F_.append(prodmesh.cached("hand:%s:%s" % (h, res), lambda V=V, F=F, res=res: prodmesh.build(V, F, res=res, pad=0.012, n_samp=400000 if k == 0 else 200000) + ("link",), res))
        ids.append(seen[h])
    return [F_[i] for i in ids], ids, F_
