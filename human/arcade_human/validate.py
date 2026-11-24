"""Check a release against the schema and against simple physical expectations.

    python -m arcade_human validate path/to/release
"""
from __future__ import annotations

import json
import os
from typing import List, Tuple

import h5py
import numpy as np

from . import schema as S
from .reader import list_mask_files

#: physical sanity tolerances (metres)
REST_Z_TOL = 0.03        # a product at rest sits on the counter: |z - h/2| (or the box's half-extent)
PALM_OBJECT_MAX = 0.25   # median palm-centre to product-centre distance while held


def _shape_ok(spec: str, arr: np.ndarray, T: int, E: int) -> bool:
    dims = spec.strip("[]").split(",")
    want = [T if d == "T" else E if d == "E" else int(d) for d in dims]
    return list(arr.shape) == want


def validate(root: str, physical: bool = True) -> Tuple[List[str], List[str]]:
    """Returns (errors, warnings)."""
    errors: List[str] = []
    warns: List[str] = []
    for rel in ("meta/info.json", "meta/episodes.jsonl", "meta/products.json", "meta/skeleton.json",
                "data/human_motion.hdf5"):
        if not os.path.exists(os.path.join(root, rel)):
            errors.append(f"missing {rel}")
    if errors:
        return errors, warns
    info = json.load(open(os.path.join(root, "meta", "info.json")))
    rows = [json.loads(l) for l in open(os.path.join(root, "meta", "episodes.jsonl")) if l.strip()]
    products = json.load(open(os.path.join(root, "meta", "products.json")))["products"]
    if info.get("n_episodes") != len(rows):
        errors.append(f"info.n_episodes={info.get('n_episodes')} but episodes.jsonl has {len(rows)} rows")

    no_masks = 0
    with h5py.File(os.path.join(root, "data", "human_motion.hdf5"), "r") as f:
        if f.attrs.get("schema_name") != S.SCHEMA_NAME:
            errors.append("hdf5 schema_name mismatch")
        eps = f["episodes"]
        if sorted(eps) != sorted(r["episode_id"] for r in rows):
            errors.append("hdf5 episode groups differ from episodes.jsonl")
        for r in rows:
            jid = r["episode_id"]
            if jid not in eps:
                continue
            g = eps[jid]
            tag = f"{jid}:"
            for a in S.EPISODE_ATTRS:
                if a not in g.attrs:
                    errors.append(f"{tag} missing attr {a}")
            if "frame_index" not in g:
                errors.append(f"{tag} missing frame_index")
                continue
            T = len(g["frame_index"])
            E = len(g["events/kind"]) if "events/kind" in g else 0
            if T != r["n_frames"]:
                errors.append(f"{tag} n_frames {r['n_frames']} != {T}")
            for path, (spec, dtype) in S.EPISODE_LAYOUT.items():
                if path not in g:
                    errors.append(f"{tag} missing {path}")
                    continue
                a = g[path]
                if not _shape_ok(spec, a, T, E):
                    errors.append(f"{tag} {path} shape {a.shape} != {spec}")
                if dtype == "str":
                    if a.dtype.kind not in "OS":
                        errors.append(f"{tag} {path} is not a string dataset")
                elif np.dtype(dtype) != a.dtype:
                    errors.append(f"{tag} {path} dtype {a.dtype} != {dtype}")
            fi = g["frame_index"][:]
            if np.any(np.diff(fi) != 1):
                errors.append(f"{tag} frame_index is not contiguous")
            # NaN <-> valid
            for pos, val in [("body/position", "body/valid")] + \
                    [(f"hand/{s}/position", f"hand/{s}/valid") for s in S.SIDES]:
                p, v = g[pos][:], g[val][:]
                if np.any(np.isnan(p[v])):
                    errors.append(f"{tag} {pos} has NaN where valid")
                if np.any(np.isfinite(p[~v])):
                    errors.append(f"{tag} {pos} has values where not valid")
            for pose, val in [(f"wrist/{s}/pose", f"wrist/{s}/valid") for s in S.SIDES] + [("object/pose", "object/valid")]:
                p, v = g[pose][:].astype(np.float64), g[val][:]
                if np.any(~np.isfinite(p[v])):
                    errors.append(f"{tag} {pose} not finite where valid")
                if v.any():
                    qn = np.linalg.norm(p[v, 3:], axis=1)
                    if np.max(np.abs(qn - 1)) > 1e-3:
                        errors.append(f"{tag} {pose} quaternion not unit (max dev {np.max(np.abs(qn - 1)):.2e})")
            st = g["object/state"][:]
            if not set(np.unique(st)) <= set(S.OBJECT_STATES):
                errors.append(f"{tag} unknown object/state values {sorted(set(np.unique(st)))}")
            ef = g["events/frame"][:]
            ek = [x.decode() if isinstance(x, bytes) else x for x in g["events/kind"][:]]
            if np.any((ef < 0) | (ef >= T)):
                errors.append(f"{tag} event frame out of range")
            if np.any(np.diff(ef) < 0):
                errors.append(f"{tag} events not sorted by frame")
            if not set(ek) <= set(S.EVENT_KINDS):
                errors.append(f"{tag} unknown event kinds {set(ek)}")
            if "task_kind" in g.attrs:
                from .tasks import core_handling
                cw = json.loads(g.attrs["core_window"]) if isinstance(g.attrs["core_window"], (str, bytes)) else g.attrs["core_window"]
                core = (max(int(cw[0]) - int(fi[0]), 0), min(int(cw[1]) - int(fi[0]), T))
                kind = core_handling({s: g[f"interaction/{s}/holding"][:] for s in S.SIDES}, core)[0]
                tk = g.attrs["task_kind"]
                tk = tk.decode() if isinstance(tk, bytes) else tk
                if tk != kind:
                    errors.append(f"{tag} task_kind {tk!r} does not match its holding intervals ({kind!r})")
            mesh = g.attrs["product_mesh"]
            mesh = mesh.decode() if isinstance(mesh, bytes) else mesh
            if not os.path.exists(os.path.join(root, mesh)):
                errors.append(f"{tag} mesh {mesh} missing")
            prod = g.attrs["product"]
            prod = prod.decode() if isinstance(prod, bytes) else prod
            if prod not in products:
                errors.append(f"{tag} product {prod} not in products.json")
            if r.get("segmentation"):
                sd = os.path.join(root, r["segmentation"])
                if not os.path.isdir(sd):              # masks are an optional download
                    no_masks += 1
                elif not os.path.exists(os.path.join(sd, "instances.json")):
                    errors.append(f"{tag} segmentation/instances.json missing")
                else:
                    files = list_mask_files(sd)
                    if not files:
                        errors.append(f"{tag} no masks ({S.MASKS_ZIP} or masks/)")
                    late = [f for f in files if int(f.rsplit("/", 1)[-1][:-4]) >= T]
                    if late:
                        errors.append(f"{tag} mask {late[0]} beyond episode")

            # events vs holding intervals (warn: two independent labels that should agree)
            for f_, h_, k_ in zip(g["events/frame"][:], g["events/hand"][:], g["events/kind"][:]):
                h_ = h_.decode() if isinstance(h_, bytes) else h_
                k_ = k_.decode() if isinstance(k_, bytes) else k_
                hold = g[f"interaction/{h_}/holding"][:]
                ok = hold[f_] if k_ == "grasp" else (hold[max(f_ - 1, 0)] and (f_ + 1 >= T or not hold[f_ + 1]))
                if not ok:
                    warns.append(f"{tag} {k_} ({h_}) at frame {f_} disagrees with interaction/{h_}/holding")
            if physical:
                op = g["object/pose"][:]
                ov = g["object/valid"][:]
                dims = json.loads(g.attrs["product_dims"])
                shape = g.attrs["product_shape"]
                rest = ov & ((st == 0) | (st == 3))
                if rest.any():
                    # a product may rest on any face: upright or lying cylinder, any box face
                    half = [dims["h"] / 2, dims["r"]] if shape == "cylinder" else \
                        [dims.get("l", 0) / 2, dims.get("w", 0) / 2, dims.get("h", 0) / 2]
                    dz = np.min(np.abs(np.median(op[rest, 2]) - np.array(half)))
                    if dz > REST_Z_TOL:
                        warns.append(f"{tag} resting product centre z={np.median(op[rest, 2]):.3f} "
                                     f"vs half extents {np.round(half, 3).tolist()}")
                for k, s in ((1, "left"), (2, "right")):
                    m = ov & (st == k)
                    if m.sum() >= 3:
                        h = g[f"hand/{s}/position"][:][:, [0, 5, 9, 17]]
                        hv = g[f"hand/{s}/valid"][:][:, [0, 5, 9, 17]]
                        ok = m & hv.all(axis=1)
                        if not ok.any():
                            continue
                        palm = h[ok].mean(axis=1)
                        d = np.linalg.norm(palm - op[ok, :3], axis=1)
                        if np.median(d) > PALM_OBJECT_MAX:
                            warns.append(f"{tag} {s} palm-product median distance {np.median(d):.3f} m while held")
    if no_masks:
        warns.append(f"{no_masks} episode(s) without their segmentation/ folder: the masks were not downloaded")
    return errors, warns
