"""Signed distance field of the product mesh: a grid SDF and normals in product coordinates (mesh bbox centre,
mesh_perm axes). Without a mesh, the same grid is built from a primitive (box or cylinder) with the product
dimensions. Grids are cached on disk (ARCADE_CACHE)."""
import hashlib, json, os
import numpy as np
from scipy.ndimage import label, map_coordinates
from scipy.spatial import cKDTree

CACHE = os.environ.get("ARCADE_CACHE", os.path.join(os.path.expanduser("~"), ".cache", "arcade_retarget", "product_mesh"))
RES, PAD = 0.0015, 0.05


def read_obj(p):
    V, F = [], []
    for l in open(p, errors="replace"):
        if l.startswith("v "): V.append([float(x) for x in l.split()[1:4]])
        elif l.startswith("f "):
            ix = [int(t.split("/")[0]) for t in l.split()[1:]]; ix = [i - 1 if i > 0 else len(V) + i for i in ix]
            F += [(ix[0], ix[k], ix[k + 1]) for k in range(1, len(ix) - 1)]
    return np.array(V, float), np.array(F, int)


def surface_samples(V, F, n, seed=0):
    """Area-weighted surface samples and their (outward) face normals."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]; N = np.cross(b - a, c - a); ar = 0.5 * np.linalg.norm(N, axis=1)
    if np.sum(np.einsum("ij,ij->i", a - a.mean(0), np.cross(b - a.mean(0), c - a.mean(0)))) < 0: N = -N   # negative signed volume = faces point inward
    N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12); rng = np.random.default_rng(seed)
    k = rng.choice(len(F), n, p=ar / ar.sum()); u, v = rng.random(n), rng.random(n); f = u + v > 1; u[f], v[f] = 1 - u[f], 1 - v[f]
    return a[k] + u[:, None] * (b[k] - a[k]) + v[:, None] * (c[k] - a[k]), N[k]


def _prim_sdf(L, dm):
    if dm["shape"] == "box":
        q = np.abs(L) - np.array([dm["l"], dm["w"], dm["h"]]) / 2; return np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(q.max(-1), 0)
    rr = np.linalg.norm(L[..., :2], axis=-1) - dm["r"]; zz = np.abs(L[..., 2]) - dm["h"] / 2
    return np.hypot(np.maximum(rr, 0), np.maximum(zz, 0)) + np.minimum(np.maximum(rr, zz), 0)


def build(V, F, res=RES, pad=PAD, dm=None, n_samp=600000):
    """Mesh (V, F) or dimension primitive (dm) → (grid origin, signed distance grid)."""
    if V is not None: lo, hi = V.min(0), V.max(0)
    else:
        e = np.array([dm["l"], dm["w"], dm["h"]]) / 2 if dm["shape"] == "box" else np.array([dm["r"], dm["r"], dm["h"] / 2]); lo, hi = -e, e
    o = lo - pad; shp = np.ceil((hi - lo + 2 * pad) / res).astype(int) + 1
    g = [o[k] + res * np.arange(shp[k]) for k in range(3)]; X = np.stack(np.meshgrid(*g, indexing="ij"), -1).reshape(-1, 3)
    if V is None: return o, _prim_sdf(X, dm).reshape(shp)
    S, N = surface_samples(V, F, n_samp); tr = cKDTree(S); D, d0, C = np.empty(len(X)), np.empty(len(X)), 400000
    for s in range(0, len(X), C):
        d, i = tr.query(X[s:s + C], k=8, workers=-1); vote = np.sign(np.einsum("pkj,pkj->pk", X[s:s + C, None] - S[i], N[i])).sum(1)
        d0[s:s + C] = d[:, 0]; D[s:s + C] = d[:, 0] * np.where(vote < 0, -1.0, 1.0)
    far = (d0 > 1.5 * res).reshape(shp); out, _ = label(far)
    edge = np.unique(np.concatenate([out[0].ravel(), out[-1].ravel(), out[:, 0].ravel(), out[:, -1].ravel(), out[:, :, 0].ravel(), out[:, :, -1].ravel()]))
    inside = far & ~np.isin(out, edge[edge > 0])   # far cells not connected to the grid boundary = inside (fixes the sign where normals are inconsistent)
    D = D.reshape(shp); D[far] = np.where(inside[far], -np.abs(D[far]), np.abs(D[far])); return o, D


class Field:
    """Points L (..., 3) in grid coordinates → signed distance (m) and normal. Outside the grid: value at the nearest grid point + distance outside."""
    def __init__(self, o, G, src, res=RES):
        self.o, self.G, self.src, self.res, self.n = np.asarray(o, float), np.asarray(G, np.float64), src, float(res), np.array(G.shape) - 1
        self.Gd = [np.ascontiguousarray(x) for x in np.gradient(self.G, self.res)]
    def _idx(self, L):
        u = (np.asarray(L, float).reshape(-1, 3) - self.o) / self.res; return u, np.clip(u, 0, self.n)
    def __call__(self, L):
        sh = np.shape(L)[:-1]; u, c = self._idx(L)
        return (map_coordinates(self.G, c.T, order=1, mode="nearest") + self.res * np.linalg.norm(u - c, axis=1)).reshape(sh)
    def normal(self, L):
        sh = np.shape(L)[:-1]; u, c = self._idx(L)
        g = np.stack([map_coordinates(G, c.T, order=1, mode="nearest") for G in self.Gd], 1) + (u - c)
        return (g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)).reshape(sh + (3,))


def cached(key, make, res):
    """Load the grid for the string key from the disk cache, or build it with make() and write it atomically."""
    cp = os.path.join(CACHE, hashlib.md5(key.encode()).hexdigest()[:16] + ".npz")
    if os.path.exists(cp): z = np.load(cp); return Field(z["o"], z["G"], str(z["src"]), res)
    o, G, src = make(); os.makedirs(CACHE, exist_ok=True); tmp = cp + ".%d.tmp.npz" % os.getpid()
    np.savez_compressed(tmp, o=o, G=G.astype(np.float32), src=src); os.replace(tmp, cp); return Field(o, G.astype(np.float32), src, res)


_F = {}
def field(meta):
    """Product Field from episode metadata: 'dims' and, when available, 'mesh_file' (a baked product mesh of
    the ARCADE-Checkout-Human release, already in the product frame) with its axis permutation 'mesh_perm'."""
    dm = meta["dims"]; p = meta.get("mesh_file"); perm = list(meta.get("mesh_perm") or [0, 1, 2])
    has = bool(p) and os.path.exists(p)
    key = json.dumps([p, perm, os.path.getmtime(p), RES, PAD] if has else [dm, RES, PAD], sort_keys=True)
    if key not in _F:
        def make():
            if not has: return build(None, None, dm=dm) + ("prim:%s" % dm["shape"],)
            V, F = read_obj(p)
            # The release bakes a proper rotation (x negated for odd permutations); the released robot data
            # used the plainly permuted mesh, so the negation is undone here to reproduce it exactly.
            if _odd(perm): V = V * np.array([-1.0, 1.0, 1.0])
            return build(V, F) + ("mesh:%s:%s" % (os.path.basename(p), "".join(map(str, perm))),)
        _F[key] = cached(key, make, RES)
    return _F[key]


def _odd(perm):
    perm, n = list(perm), 0
    for i in range(len(perm)):
        for j in range(i + 1, len(perm)):
            n += perm[i] > perm[j]
    return n % 2 == 1
