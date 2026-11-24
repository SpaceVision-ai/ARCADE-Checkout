"""Hand rig: fits the HX5-D20 robot hand to the 21 human hand landmarks. Fingertip positions are the primary target,
finger segment directions and palm orientation are secondary; joint limits, no finger-to-finger interpenetration
(self-collision terms) and frame-to-frame continuity are handled by the rig. The robot hand is larger than the human
hand, so the solver chooses the wrist position (it sits behind the human wrist and the fingers flex slightly more).
Hand frame = link7 orientation + centre of the four finger MCPs (the mcp_<side> frame tracked by the arm IK)."""
import hashlib, json, os
import numpy as np, pinocchio as pin
from scipy.optimize import least_squares
from scipy.optimize._numdiff import approx_derivative
from arcade_retarget.ffw_sh5 import hand_mesh as HMS, product_mesh as PMS

H_CHAIN = np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20]])   # human keypoints (thumb..little), last = fingertip
R_JOINT = np.array([[2, 3, 4], [6, 7, 8], [10, 11, 12], [14, 15, 16], [18, 19, 20]]) - 1   # three robot link origins (joints), followed by the fingertip (finger_end)
H_MCP, R_MCP = (5, 9, 13, 17), (6, 10, 14, 18)


def basis(f, a):
    """Columns = forward (f), side (a made orthogonal to f), f×a."""
    f = f / np.linalg.norm(f); a = a - f * (a @ f); a = a / np.linalg.norm(a); return np.stack([f, a, np.cross(f, a)], 1)


def skew(w):
    K = np.zeros(w.shape[:-1] + (3, 3)); K[..., 0, 1], K[..., 0, 2], K[..., 1, 2] = -w[..., 2], w[..., 1], -w[..., 0]; return K - np.swapaxes(K, -1, -2)


def exp3(w):
    """(B,3) rotation vectors → (B,3,3) rotation matrices."""
    th = np.linalg.norm(w, axis=-1)[..., None, None]; K = skew(w); ts = np.maximum(th, 1e-9)
    a = np.where(th > 1e-9, np.sin(ts) / ts, 1.0); b = np.where(th > 1e-9, (1 - np.cos(ts)) / ts ** 2, 0.5); return np.eye(3) + a * K + b * (K @ K)


def log3(R):
    """(B,3,3) → (B,3) rotation vectors; not for angles near π (meant for small differences)."""
    th = np.arccos(np.clip((np.trace(R, axis1=-2, axis2=-1) - 1) / 2, -1, 1)); th = np.minimum(th, np.pi - 1e-3)
    v = np.stack([R[..., 2, 1] - R[..., 1, 2], R[..., 0, 2] - R[..., 2, 0], R[..., 1, 0] - R[..., 0, 1]], -1)
    return v * np.where(th > 1e-6, th / (2 * np.sin(np.maximum(th, 1e-6))), 0.5)[..., None]


def soft(r, axis=None):
    """soft-L1 as a residual: its square is 2(√(1+r²)−1). With axis, uses the vector norm along that axis (per fingertip point)."""
    n = np.abs(r) if axis is None else np.linalg.norm(r, axis=axis, keepdims=True)
    return r * np.where(n > 1e-9, np.sqrt(2 * (np.sqrt(1 + n ** 2) - 1)) / np.maximum(n, 1e-9), 1.0)


def human_targets(X, B_r):
    """Human hand landmarks (n,21,3) → fingertips (n,5,3), segment directions (n,5,3,3), palm orientation target (hand-frame rotation) (n,3,3)."""
    C = X[:, H_CHAIN]; tip = C[:, :, 3]; D = np.diff(C, axis=2); U = D / np.maximum(np.linalg.norm(D, axis=-1, keepdims=True), 1e-9)
    mc = X[:, list(H_MCP)].mean(1); Rp = np.array([basis(m - x[0], x[5] - x[17]) @ B_r.T for m, x in zip(mc, X)]); return tip, U, Rp


class HandRig:
    """One hand: kinematics (links and fingertips in the hand frame), collision-mesh samples, link-SDF self-collision, fitting to the human hand."""
    def __init__(self, hm, urdf, mesh_root, side, W, spacing=0.005, base_spacing=0.008, plan_k=50, self_k=50):
        s = side[0]; d = hm.createData(); q0 = pin.neutral(hm); pin.forwardKinematics(hm, d, q0); pin.updateFramePlacements(hm, d)
        F = lambda n: d.oMf[hm.getFrameId(n)]; L7 = F("arm_%s_link7" % s); inv = L7.inverse(); P = lambda n: (inv * F(n)).translation
        self.side, self.W = side, W
        self.mcp = np.mean([P("finger_%s_link%d" % (s, i)) for i in R_MCP], axis=0)
        self.B = basis(self.mcp - P("hx5_d20_%s_base" % side), P("finger_%s_link6" % s) - P("finger_%s_link18" % s))   # same definition as the human palm frame (wrist → MCP centre, little → index MCP)
        self.T_mcp = L7 * pin.SE3(np.eye(3), self.mcp); self.mcp2hb = self.T_mcp.inverse() * F("hx5_d20_%s_base" % side)
        iq = [hm.joints[hm.getJointId("finger_%s_joint%d" % (s, j))].idx_q for j in range(1, 21)]; iv = [hm.joints[hm.getJointId("finger_%s_joint%d" % (s, j))].idx_v for j in range(1, 21)]
        self.lo, self.hi, self.vel = hm.lowerPositionLimit[iq].copy(), hm.upperPositionLimit[iq].copy(), hm.velocityLimit[iv].copy()
        # finger chain constants (hand frame): parent index, fixed placement, rotation axis; fingertip frames
        J = [hm.getJointId("finger_%s_joint%d" % (s, k)) for k in range(1, 21)]; par = [J.index(hm.parents[j]) if hm.parents[j] in J else -1 for j in J]
        assert all(p < k for k, p in enumerate(par)) and all(hm.joints[j].shortname() in ("JointModelRX", "JointModelRY", "JointModelRZ") for j in J)
        Tm_inv = self.T_mcp.inverse()
        self.M = np.array([(Tm_inv * d.oMi[hm.parents[j]] * hm.jointPlacements[j]).homogeneous if p < 0 else hm.jointPlacements[j].homogeneous for j, p in zip(J, par)])
        tf = [hm.getFrameId("finger_end_%s_link%d" % (s, i)) for i in range(1, 6)]
        self.par, self.ax = par, ["XYZ".index(hm.joints[j].shortname()[-1]) for j in J]; self._chain_groups(); self.tp = [J.index(hm.frames[f].parentJoint) for f in tf]; self.tM = np.array([hm.frames[f].placement.homogeneous for f in tf])
        # collision mesh: sparse samples for path checks; link capsules, samples and local SDFs for self-collision
        names = ["hx5_d20_%s_base" % side] + ["finger_%s_link%d" % (s, i) for i in range(1, 21)]; tris = HMS.link_tris(urdf, mesh_root, names)
        g = self._mesh_geom(hm, urdf, mesh_root, side, names, tris, spacing, base_spacing, plan_k, self_k)
        self.base_pts = g["sel0"] @ self.mcp2hb.rotation.T + self.mcp2hb.translation; self.link_pts = g["sel"][1:]; self.lab = np.concatenate([np.full(len(x), k) for k, x in enumerate(g["sel"])])
        self.Tb = self.mcp2hb.homogeneous; self.ce, self.cr, self.Ps = g["ce"], g["cr"], g["Ps"]; _, self.fid, self.LFu = HMS.link_fields(names, tris); self.fid_a = np.array(self.fid); self._pack()
        # self-collision pairs: base–link, links of different fingers, non-adjacent segments of the same finger. Pairs already overlapping at the zero pose (root housings) are dropped; pairs closer than the clearance at the zero pose use that distance as their clearance
        fing = lambda k: (k - 1) // 4
        P = np.array([(a, b) for a in range(21) for b in range(a + 1, 21) if a == 0 or fing(a) != fing(b) or b - a >= 2]); self.pairs, self.gap = P, np.full(len(P), W["self_gap"])
        d0 = self.pair_dist(self.rows(np.zeros((1, 20))), np.arange(len(P)))[0].reshape(2, -1).min(0); keep = d0 > -0.0005
        self.pairs, self.gap = P[keep], np.minimum(W["self_gap"], np.maximum(d0[keep], 0.0))

    @staticmethod
    def _mesh_geom(hm, urdf, mesh_root, side, names, tris, spacing, base_spacing, plan_k, self_k):
        """Link samples (sparse samples for path checks, self-collision samples) and capsules. Disk-cached when meshes and arguments match (identical values)."""
        key = hashlib.md5(json.dumps([side, spacing, base_spacing, plan_k, self_k, "v1"]).encode() + b"".join(tris[n][0].tobytes() for n in names)).hexdigest()[:16]
        cp = os.path.join(PMS.CACHE, "handgeom_%s.npz" % key); cat = lambda L: (np.concatenate(L), np.array([len(x) for x in L]))
        split = lambda a, n: np.split(a, np.cumsum(n)[:-1])
        if os.path.exists(cp):
            z = np.load(cp); return dict(sel0=z["sel0"], sel=split(z["sel"], z["sel_n"]), ce=z["ce"], cr=z["cr"], Ps=split(z["Ps"], z["Ps_n"]))
        G = HMS.Hand(hm, urdf, mesh_root, side, spacing=spacing, base_spacing=base_spacing, self_k=self_k)
        sel = [G.P[k][np.sort(HMS.fps(P_, (4 if k == 0 else 1) * plan_k))] for k, P_ in enumerate(G.P)]
        out = dict(sel0=sel[0], sel=sel, ce=np.array([G.cap[k][0] for k in range(21)]), cr=np.array([G.cap[k][1] for k in range(21)]), Ps=list(G.Ps))
        (S, Sn), (Q, Qn) = cat(sel), cat(out["Ps"]); os.makedirs(PMS.CACHE, exist_ok=True); tmp = cp + ".%d.tmp.npz" % os.getpid()
        np.savez(tmp, sel0=out["sel0"], sel=S, sel_n=Sn, ce=out["ce"], cr=out["cr"], Ps=Q, Ps_n=Qn); os.replace(tmp, cp); return out

    def _chain_groups(self):
        """For rows(): joints grouped by rotation axis, and (joint, parent) grouped by chain depth."""
        self.ax_groups = [(a, [(1, 2), (2, 0), (0, 1)][a], np.array([k for k in range(20) if self.ax[k] == a])) for a in range(3) if a in self.ax]
        dep = []
        for k in range(20): dep.append(0 if self.par[k] < 0 else dep[self.par[k]] + 1)
        self.levels = []
        for L in range(max(dep) + 1):
            ks = np.array([k for k in range(20) if dep[k] == L]); self.levels.append((ks, None if L == 0 else np.array([self.par[k] for k in ks])))
        assert all((self.par[k] < 0) == (L == 0) for L, (ks, _) in enumerate(self.levels) for k in ks)

    def rows(self, Q, tips=False):
        """Finger joints (B,20) → poses of links 1..20 in the hand frame (B,20,4,4); with tips, also fingertips (B,5,3)."""
        Q = np.asarray(Q, float); B = len(Q); H = np.empty((B, 20, 4, 4)); c, s_ = np.cos(Q), np.sin(Q); Rk = np.zeros((B, 20, 4, 4)); Rk[:, :, 3, 3] = 1.0
        for a, (i, j), ks in self.ax_groups:
            Rk[:, ks, a, a] = 1.0; Rk[:, ks, i, i] = c[:, ks]; Rk[:, ks, j, j] = c[:, ks]; Rk[:, ks, i, j] = -s_[:, ks]; Rk[:, ks, j, i] = s_[:, ks]
        for ks, ps in self.levels:   # all five fingers at once, one chain depth at a time
            H[:, ks] = (self.M[ks] if ps is None else H[:, ps] @ self.M[ks]) @ Rk[:, ks]
        if not tips: return H
        return H, (H[:, self.tp] @ self.tM[None])[:, :, :3, 3]

    def chain_pts(self, Q, Ht=None):
        """(B,5,4,3) chain points in the hand frame (three joints + fingertip), paired with the human H_CHAIN. Ht = precomputed rows(Q, tips=True)."""
        H, tp = self.rows(Q, tips=True) if Ht is None else Ht; return np.concatenate([H[:, R_JOINT][..., :3, 3], tp[:, :, None]], 2), H

    def mesh_pts(self, q):
        """Sparse hand collision-mesh samples for one pose (hand frame) and their link indices (base = 0)."""
        H = self.rows(np.asarray(q, float)[None]); R = np.swapaxes(H[0, :, :3, :3], -1, -2); t = H[0, :, :3, 3]
        return np.concatenate([self.base_pts] + [self.link_pts[k] @ R[k] + t[k] for k in range(20)]), self.lab

    def _link_T(self, H):
        return np.concatenate([np.broadcast_to(self.Tb, (len(H), 1, 4, 4)), H], 1)

    def self_cands(self, Hs, margin):
        """Indices of pairs whose bounding capsules come within margin in any of the poses."""
        a, b = self.pairs[:, 0], self.pairs[:, 1]; m = np.zeros(len(a), bool)
        for H in Hs:
            T = self._link_T(H); E = np.einsum("bkij,kej->bkei", T[:, :, :3, :3], self.ce) + T[:, :, None, :3, 3]
            m |= (HMS.seg_dist(E[:, a, 0], E[:, a, 1], E[:, b, 0], E[:, b, 1]) - self.cr[a] - self.cr[b] < margin).any(0)
        return np.nonzero(m)[0]

    def _pack(self):
        """Pack link SDF grids into one array (one lookup per point by grid index), group links with equal sample counts, ancestor joints per link."""
        F = self.LFu; self.g_flat = np.concatenate([f.G.ravel() for f in F]); self.g_off = np.r_[0, np.cumsum([f.G.size for f in F])[:-1]].astype(np.int64)
        self.g_st = np.array([[f.G.shape[1] * f.G.shape[2], f.G.shape[2], 1] for f in F], np.int64)
        self.g_o = np.array([f.o for f in F]); self.g_res = np.array([f.res for f in F]); self.g_n = np.array([f.n for f in F], np.int64)
        self.plen = np.array([len(P) for P in self.Ps]); self.PG = {L: np.array([P if len(P) == L else np.zeros((L, 3)) for P in self.Ps]) for L in np.unique(self.plen)}
        self.anc = np.zeros((20, 21))
        for k in range(1, 21):
            j = k - 1
            while j >= 0: self.anc[j, k] = 1.0; j = self.par[j]

    def _sdf(self, X, f, grad=False):
        """Signed distance at points X (..., 3) in grid coordinates (trilinear; outside the grid, border value + distance outside), f = grid index (broadcast over the leading shape of X).
        With grad, also the gradient w.r.t. X (..., 3) (trilinear derivative inside the grid, outward direction outside)."""
        r = self.g_res[f]; o = self.g_o[f]; n = self.g_n[f]; st = self.g_st[f]; I, Wt, O = [], [], []
        for k in range(3):   # per axis: lower/upper cell index (times stride) and weights
            u = (X[..., k] - o[..., k]) / r; c = np.clip(u, 0, n[..., k]); fl = np.floor(c); i0 = fl.astype(np.int64); w0 = 1.0 - (c - fl)
            I.append((i0 * st[..., k], np.minimum(i0 + 1, n[..., k]) * st[..., k])); Wt.append((w0, 1.0 - w0)); O.append(u - c)
        base = self.g_off[f]; V = {}; t = 0.0
        for p in (0, 1):
            for q in (0, 1):
                ab = base + I[0][p] + I[1][q]; wpq = Wt[0][p] * Wt[1][q]
                for s_ in (0, 1): V[p, q, s_] = v = self.g_flat[ab + I[2][s_]]; t = t + v * wpq * Wt[2][s_]
        dout = np.sqrt(O[0] ** 2 + O[1] ** 2 + O[2] ** 2); val = t + r * dout
        if not grad: return val
        g = []
        for k in range(3):   # upper − lower cell difference along axis k, weighted by the other two axes
            j, l = [x for x in range(3) if x != k]; acc = 0.0
            for a_ in (0, 1):
                for b_ in (0, 1):
                    hi_, lo_ = [None] * 3, [None] * 3; hi_[k], lo_[k] = 1, 0; hi_[j] = lo_[j] = a_; hi_[l] = lo_[l] = b_
                    acc = acc + (V[tuple(hi_)] - V[tuple(lo_)]) * Wt[j][a_] * Wt[l][b_]
            g.append(np.where(O[k] == 0.0, acc / r, 0.0) + O[k] / np.maximum(dout, 1e-12))
        return val, np.stack(g, -1)

    def _pair(self, T, ci, grad=False):
        """Softmin distance of pairs ci for link poses T (B,21,4,4), (B, 2·n_pairs): first half = first-link samples against the second link's mesh, second half the reverse.
        With grad, returns (distance, Σw∇ and Σw x×∇ in field-link coordinates, each (B, 2·n_pairs, 3), sample-link and field-link indices)."""
        c_ = self.pairs[ci]; U, V = np.r_[c_[:, 0], c_[:, 1]], np.r_[c_[:, 1], c_[:, 0]]; tau = self.W["tau"]
        TU, TV = T[:, U], T[:, V]; RvT = np.swapaxes(TV[..., :3, :3], -1, -2); M = np.swapaxes(RvT @ TU[..., :3, :3], -1, -2); off = (RvT @ (TU[..., :3, 3] - TV[..., :3, 3])[..., None])[..., 0]
        val = np.empty((len(T), len(U))); A, C = np.empty((len(T), len(U), 3)), np.empty((len(T), len(U), 3))
        for L, P in self.PG.items():
            ig = np.nonzero(self.plen[U] == L)[0]
            if not len(ig): continue
            X = P[U[ig]] @ M[:, ig] + off[:, ig, None, :]; r = self._sdf(X, self.fid_a[V[ig]][:, None], grad); D, g = r if grad else (r, None)
            m = D.min(-1); e = np.exp(-(D - m[..., None]) / tau); S = e.sum(-1); val[:, ig] = m - tau * np.log(S)
            if grad: wg = (e / S[..., None])[..., None] * g; A[:, ig] = wg.sum(-2); O = np.einsum("...ka,...kb->...ab", X, wg); C[:, ig] = np.stack([O[..., 1, 2] - O[..., 2, 1], O[..., 2, 0] - O[..., 0, 2], O[..., 0, 1] - O[..., 1, 0]], -1)
        return (val, A, C, U, V) if grad else val

    def pair_dist(self, H, ci):
        """Distance (m) for each pair in ci, measured with each other's local SDF, (B, 2·n_pairs)."""
        return self._pair(self._link_T(H), ci) if len(ci) else np.zeros((len(H), 0))

    def pair_grad(self, H, ci):
        """For one pose H (20,4,4): distances of pairs ci (2·n_pairs,) and their gradient w.r.t. the finger joints (2·n_pairs, 20)."""
        T = self._link_T(H[None]); val, A, C, U, V = self._pair(T, ci, grad=True); TV = T[0, V]
        Rv = TV[:, :3, :3]; Sg = np.einsum("nij,nj->ni", Rv, A[0]); Syg = np.einsum("nij,nj->ni", Rv, C[0]) + np.cross(TV[:, :3, 3], Sg)   # softmin gradient sums (hand frame): Σw∇, Σw y×∇
        ax = H[np.arange(20), :3, self.ax]; org = H[:, :3, 3]; sgn = self.anc[:, U].T - self.anc[:, V].T   # joint axes and origins; + if the joint moves only the sample link, − if only the field link
        return val[0], sgn * (Syg @ ax.T - Sg @ np.cross(ax, org).T)

    def self_pen(self, H, ci):
        """Clearance shortfall (m), (B, 2·n_pairs)."""
        return np.maximum(0.0, np.r_[self.gap[ci], self.gap[ci]] - self.pair_dist(H, ci))

    def self_max(self, q):
        H = self.rows(np.asarray(q, float)[None]); c = self.self_cands([H], 0.0); return float(self.self_pen(H, c).max()) if len(c) else 0.0

    def fit(self, tip, U, Rp, pose0, q0, prev=None, fixed=False, qbox=None):
        """Fit one frame: tip (5,3) and U (5,3,3) world targets, Rp = palm orientation target (None = none), pose0 = (R, p) start (wrist held fixed if fixed),
        prev = (R, p, q) extrapolated from the previous frames (continuity), qbox = finger joint bounds (velocity limit). Returns (R, p, q, cost)."""
        W = self.W; lo, hi = (self.lo, self.hi) if qbox is None else qbox; R0, p0 = pose0
        def unpack(X):
            if fixed: return np.broadcast_to(R0, (len(X), 3, 3)), np.broadcast_to(p0, (len(X), 3)), X
            return exp3(X[:, 3:6]) @ R0, p0 + X[:, :3], X[:, 6:]
        def res(X, Ht=None):
            R, p, Q = unpack(X); C, _ = self.chain_pts(Q, Ht); Wc = np.einsum("bij,bfkj->bfki", R, C) + p[:, None, None]; B = len(X)
            D = np.diff(Wc, axis=2); Ur = D / np.linalg.norm(D, axis=-1, keepdims=True); e = (Wc[:, :, 3] - tip) / W["sig_tip"]
            r = [soft(e, 2).reshape(B, -1), soft((Ur - U) / W["sig_dir"]).reshape(B, -1)]   # tracking, shape and continuity are soft-L1; only self-collision is squared (so it dominates)
            if not fixed and Rp is not None: r.append(soft(log3(Rp.T @ R) / W["sig_palm"]))
            if prev is not None:
                r.append(soft((Q - prev[2]) / W["sig_tq"]))
                if not fixed: r += [soft((p - prev[1]) / W["sig_tp"]), soft(log3(np.swapaxes(prev[0], -1, -2) @ R) / W["sig_tr"])]
            return np.concatenate(r, 1)
        x0 = np.clip(q0, lo, hi) if fixed else np.r_[np.zeros(6), np.clip(q0, lo, hi)]
        bl, bh = (lo, hi) if fixed else (np.r_[-np.inf * np.ones(6), lo], np.r_[np.inf * np.ones(6), hi])
        cands = np.zeros(0, int); best = None; k0 = 0 if fixed else 6; memo = {}
        batch = lambda _, xs: res(np.array(list(xs)))
        def full(x):   # other residuals + self-collision residuals (squared penalty); self-collision gradient is analytic
            key = x.tobytes()
            if key not in memo:
                Ht = self.rows(x[k0:][None], tips=True); v, gq = self.pair_grad(Ht[0][0], cands); gap = np.r_[self.gap[cands], self.gap[cands]]
                if len(memo) > 4: memo.clear()
                memo[key] = (res(x[None], Ht)[0], W["g_self"] * np.maximum(0.0, gap - v) / 0.001, np.where((gap - v > 0)[:, None], -W["g_self"] / 0.001 * gq, 0.0))
            return memo[key]
        def jac(x):
            r0, _, gs = full(x); J = np.zeros((len(r0) + len(gs), len(x)))
            J[:len(r0)] = approx_derivative(lambda z: res(z[None])[0], x, method="2-point", f0=r0, bounds=(bl, bh), workers=batch); J[len(r0):, k0:] = gs; return J   # other rows: same values as least_squares' finite differences
        for _ in range(3):   # add nearby self-collision pairs only when the solved pose penetrates, then re-solve from the start point (extrapolated from the previous frames)
            if len(cands): r = least_squares(lambda x: np.r_[full(x)[0], full(x)[1]], x0, jac=jac, bounds=(bl, bh), max_nfev=W["nfev"], x_scale="jac", ftol=1e-4, xtol=1e-4)
            else: r = least_squares(lambda x: res(x[None])[0], x0, bounds=(bl, bh), max_nfev=W["nfev"], x_scale="jac", ftol=1e-4, xtol=1e-4, workers=batch)
            H = self.rows((r.x if fixed else r.x[6:])[None]); c0 = self.self_cands([H], 0.0); pen = self.self_pen(H, c0).max() if len(c0) else 0.0
            if best is None or (pen, r.cost) < best[1:]: best = (r, pen, r.cost)
            if pen <= W["self_tol"]: break
            new = np.setdiff1d(self.self_cands([H], W["self_margin"]), cands)
            if not len(new): break
            cands = np.r_[cands, new]; memo.clear()
        best = best[0]
        R, p, Q = unpack(best.x[None]); return np.array(R[0]), np.array(p[0]), np.array(Q[0]), float(best.cost)

    def track(self, tip, U, Rp=None, pose=None, q_init=None, vmax=0.2):
        """Fit frames in order: continuity is anchored on the pose extrapolated from the previous two frames; finger joints stay within vmax (rad) of the previous frame.
        pose = per-frame fixed wrist (R (n,3,3), p (n,3)) (None = solve the wrist too), q_init = per-frame start finger joints (default: from the previous frames). Returns (R, p, q, cost)."""
        n = len(tip); fixed = pose is not None; Rs, ps, Qs, cost = np.zeros((n, 3, 3)), np.zeros((n, 3)), np.zeros((n, 20)), np.zeros(n)
        for t in range(n):
            if t == 0:
                seeds = [np.clip(q_init[0], self.lo, self.hi)] if q_init is not None else [np.clip(f * self.hi + (1 - f) * self.lo, self.lo, self.hi) for f in (0.0, 0.3, 0.6)]
                best = None
                for qs in seeds:   # first frame: try several start hand shapes
                    if fixed: P0 = (pose[0][0], pose[1][0])
                    else: C, _ = self.chain_pts(qs[None]); P0 = (Rp[0], tip[0].mean(0) - Rp[0] @ C[0, :, 3].mean(0))
                    r = self.fit(tip[0], U[0], None if fixed else Rp[0], P0, qs, None, fixed)
                    if best is None or r[3] < best[3]: best = r
            else:
                k2 = max(t - 2, 0); R1, p1, q1 = Rs[t - 1], ps[t - 1], Qs[t - 1]
                pred = (R1 @ exp3(0.5 * log3(Rs[k2].T @ R1)), p1 + 0.5 * (p1 - ps[k2]), q1 + 0.5 * (q1 - Qs[k2]))
                box = (np.maximum(self.lo, q1 - vmax), np.minimum(self.hi, q1 + vmax)); qs = q_init[t] if q_init is not None else pred[2]
                P0 = (pose[0][t], pose[1][t]) if fixed else pred[:2]
                best = self.fit(tip[t], U[t], None if fixed else Rp[t], P0, np.clip(qs, *box), pred, fixed, box)
            Rs[t], ps[t], Qs[t], cost[t] = best
        return Rs, ps, Qs, cost
