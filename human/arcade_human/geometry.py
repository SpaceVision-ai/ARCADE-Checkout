"""Small, dependency-free geometry helpers (numpy only)."""
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from .schema import HAND_INDEX_MCP, HAND_MIDDLE_MCP, HAND_PINKY_MCP, HAND_WRIST


def matrix_to_quat_xyzw(R: np.ndarray) -> np.ndarray:
    """Rotation matrices (..., 3, 3) -> unit quaternions (..., 4), order xyzw, qw >= 0."""
    R = np.asarray(R, dtype=np.float64)
    shp = R.shape[:-2]
    R = R.reshape(-1, 3, 3)
    q = np.empty((len(R), 4))
    tr = R[:, 0, 0] + R[:, 1, 1] + R[:, 2, 2]
    for i, m in enumerate(R):
        if tr[i] > 0:
            s = np.sqrt(tr[i] + 1.0) * 2
            q[i] = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
            q[i] = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
        elif m[1, 1] > m[2, 2]:
            s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
            q[i] = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
        else:
            s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
            q[i] = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    q[q[:, 3] < 0] *= -1
    return q.reshape(shp + (4,))


def quat_xyzw_to_matrix(q: np.ndarray) -> np.ndarray:
    """Quaternions (..., 4) xyzw -> rotation matrices (..., 3, 3)."""
    q = np.asarray(q, dtype=np.float64)
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], -2)


def pose_to_matrix(pose: np.ndarray) -> np.ndarray:
    """[x, y, z, qx, qy, qz, qw] (..., 7) -> homogeneous transforms (..., 4, 4). NaN stays NaN."""
    pose = np.asarray(pose, dtype=np.float64)
    T = np.zeros(pose.shape[:-1] + (4, 4))
    T[..., :3, :3] = quat_xyzw_to_matrix(pose[..., 3:7])
    T[..., :3, 3] = pose[..., :3]
    T[..., 3, 3] = 1.0
    return T


def matrix_to_pose(T: np.ndarray) -> np.ndarray:
    """Homogeneous transforms (..., 4, 4) -> [x, y, z, qx, qy, qz, qw]. Non-finite rows -> NaN."""
    T = np.asarray(T, dtype=np.float64)
    flat = T.reshape(-1, 4, 4)
    out = np.full((len(flat), 7), np.nan)
    ok = np.all(np.isfinite(flat.reshape(len(flat), -1)), axis=1)
    if ok.any():
        out[ok, :3] = flat[ok, :3, 3]
        out[ok, 3:] = matrix_to_quat_xyzw(flat[ok, :3, :3])
    return out.reshape(T.shape[:-2] + (7,))


def wrist_frames(hand: np.ndarray, valid: np.ndarray, side: str, min_width: float = 0.01
                 ) -> Tuple[np.ndarray, np.ndarray]:
    """Wrist SE(3) from 21 hand landmarks.

    hand: (T, 21, 3) positions, valid: (T, 21). Returns pose (T, 7) and valid (T,).
    Frame definition: see ``schema.WRIST_FRAME``.
    """
    T = len(hand)
    pose = np.full((T, 7), np.nan)
    need = [HAND_WRIST, HAND_INDEX_MCP, HAND_MIDDLE_MCP, HAND_PINKY_MCP]
    ok = np.all(valid[:, need], axis=1)
    w, i5, m9, p17 = (hand[:, k].astype(np.float64) for k in need)
    x = m9 - w
    across = (i5 - p17) if side == "right" else (p17 - i5)
    xn = np.linalg.norm(x, axis=1)
    ok &= xn > min_width
    x = x / np.maximum(xn, 1e-12)[:, None]
    y = across - x * np.sum(across * x, axis=1, keepdims=True)
    yn = np.linalg.norm(y, axis=1)
    ok &= yn > min_width
    y = y / np.maximum(yn, 1e-12)[:, None]
    z = np.cross(x, y)
    R = np.stack([x, y, z], axis=-1)
    if ok.any():
        pose[ok, :3] = w[ok]
        pose[ok, 3:] = matrix_to_quat_xyzw(R[ok])
    return pose, ok


def is_odd_permutation(perm: Sequence[int]) -> bool:
    perm = list(perm)
    return sum(1 for i in range(3) for j in range(i + 1, 3) if perm[i] > perm[j]) % 2 == 1


def product_axes(perm: Sequence[int]) -> np.ndarray:
    """3x3 rotation A with ``product_point = A @ (mesh_point - bbox_centre)``.

    Product axis ``i`` is mesh axis ``perm[i]``. When the permutation is odd, the product
    x axis is negated, so A is always a proper rotation (det +1). This is exactly the
    convention the 6-DoF tracker used to turn its mesh-frame pose into the released
    product pose: ``R_product = R_mesh[:, perm]``, with column 0 negated if its
    determinant is negative.
    """
    perm = list(perm)
    A = np.zeros((3, 3))
    for i, j in enumerate(perm):
        A[i, j] = 1.0
    if is_odd_permutation(perm):
        A[0] *= -1.0
    return A


def bake_obj(src: str, dst: str, perm: Sequence[int], name: str = "") -> Tuple[np.ndarray, np.ndarray]:
    """Write ``src`` OBJ re-expressed in the product frame (see ``product_axes``).

    Vertices are centred on the mesh bounding box and rotated by ``product_axes(perm)``;
    normals are rotated by the same matrix. The map is a proper rotation, so face winding,
    texture coordinates and materials are unchanged and the mesh is never a mirror image.
    `name` replaces the OBJ object name and header comment. Returns (bbox_min, bbox_max) of the
    baked vertices.
    """
    A = product_axes(perm)
    lines = open(src, errors="replace").read().splitlines()
    V = np.array([[float(x) for x in l.split()[1:4]] for l in lines if l.startswith("v ")])
    c = (V.max(0) + V.min(0)) / 2
    out = [f"# ARCADE product mesh{': ' + name if name else ''}, in the product frame (bounding-box centre)"] if name else []
    for l in lines:
        if name and l.startswith("#"):
            continue
        if name and l.startswith("o "):
            out.append(f"o {name}")
            continue
        if l.startswith("v ") or l.startswith("vn "):
            t = l.split()
            p = np.array([float(x) for x in t[1:4]])
            if t[0] == "v":
                p = p - c
            rest = " " + " ".join(t[4:]) if len(t) > 4 else ""
            out.append("%s %.6f %.6f %.6f%s" % (t[0], *(A @ p), rest))
        else:
            out.append(l)
    with open(dst, "w") as f:
        f.write("\n".join(out) + "\n")
    Vb = (V - c) @ A.T
    return Vb.min(0), Vb.max(0)


def load_obj_vertices(path: str) -> np.ndarray:
    """Vertex positions of an OBJ file (N, 3)."""
    return np.array([[float(x) for x in l.split()[1:4]] for l in open(path, errors="replace") if l.startswith("v ")])
