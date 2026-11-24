"""Product trajectory on the robot's output steps.

  python -m arcade_retarget.ffw_sh5.object_track --release REL --ik build/ffw_sh5_ik --out build/ffw_sh5_obj

Moves each episode's product pose, carrying intervals and counter onto the retargeting's output
steps, so that the robot data can be used without the human data:

* before the first grasp the product follows the human data (interpolated at the step's source frame);
* while held it rides with the robot hand: the human hand–product relation, expressed in the planned
  hand frame, is carried to the robot's actual hand frame (with both hands on it, the hand that
  carries it in the human data); changes of carrier are blended over ``settle_n`` steps;
* after a release it settles onto the nearest stable face, where the robot put it down.

The deviation of the attached product from the human product path is kept per episode
(``obj_dev`` per step, ``track`` in the JSON). Output: ``<out>.npz`` (keys ``<episode>|obj_T``,
``obj_ok``, ``obj_T_s1``, ``obj_dev``, ``obj_carrier``) and ``<out>.json``; see docs/FORMAT.md.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Optional

import numpy as np

from arcade_retarget.ffw_sh5 import object_attach as OA
from arcade_retarget.human_source import HumanSource

TORSO_HALF = 0.10   # hip keypoint to the front of the body (m), for the per-episode counter fallback
PAD = 0.12


def _fill(T):
    """Fill empty (NaN) frames with the nearest valid frame."""
    ok = np.all(np.isfinite(T.reshape(len(T), -1)), 1)
    if not ok.any():
        return None, ok
    idx = np.where(ok)[0]
    near = idx[np.abs(np.arange(len(T))[:, None] - idx[None]).argmin(1)]
    return T[near].copy(), ok


def _mix_T(A_, B_, a):
    """Between two 4×4 poses: position linear, rotation geodesic."""
    if not (np.all(np.isfinite(A_)) and np.all(np.isfinite(B_))):
        return A_ if a < 0.5 else B_
    from scipy.spatial.transform import Rotation as R_, Slerp
    M = np.eye(4)
    M[:3, :3] = Slerp([0, 1], R_.from_matrix([A_[:3, :3], B_[:3, :3]]))([a]).as_matrix()[0]
    M[:3, 3] = (1 - a) * A_[:3, 3] + a * B_[:3, 3]
    return M


def _ang(Ra, Rb, cyl):
    if cyl:
        return float(np.degrees(np.arccos(np.clip(abs(Ra[:, 2] @ Rb[:, 2]), -1, 1))))
    return float(np.degrees(np.arccos(np.clip((np.trace(Ra.T @ Rb) - 1) / 2, -1, 1))))


def export(release: str, ik_prefix: str, out_prefix: str, attach: bool = True, settle_n: int = 5,
           episodes: Optional[List[str]] = None) -> Dict:
    ik = np.load(ik_prefix + ".npz", allow_pickle=False)
    meta = json.load(open(ik_prefix + ".json"))
    all_j = sorted(k.split("|")[0] for k in ik.files if k.endswith("|frames"))
    if episodes:
        all_j = [j for j in all_j if j in set(episodes)]
    src = HumanSource(release, all_j)
    cb = meta.get("counter")   # the counter the retargeting used, if recorded
    CB_ = dict(center=[(cb["x0"] + cb["x1"]) / 2, (cb["y0"] + cb["y1"]) / 2], size=[cb["x1"] - cb["x0"], cb["y1"] - cb["y0"]],
               yaw=float(cb.get("yaw", 0.0))) if cb else None
    arr, eps = {}, {}
    for jid in all_j:
        o = src.OBJ.get(jid)
        if o is None:
            continue
        pm = src.product_meta(jid)
        fr = ik[jid + "|frames"].astype(int)
        n = len(fr)
        yaw = float(ik[jid + "|base"][3])
        of = {int(f): i for i, f in enumerate(o.frames)}
        TM = ik[jid + "|tmap"].astype(float) if jid + "|tmap" in ik.files else fr.astype(float)   # source frame (fractional) per step
        T = np.full((n, 4, 4), np.nan)
        for t, u in enumerate(TM):
            l_, h_ = int(np.floor(u)), int(np.floor(u)) + 1
            a_ = u - l_
            if l_ in of and h_ in of and a_ > 1e-6:
                T[t] = _mix_T(o.T[of[l_]], o.T[of[h_]], a_)
            elif int(round(u)) in of:
                T[t] = o.T[of[int(round(u))]]
        T, okT = _fill(T)
        if T is None:
            continue
        if CB_ is None:   # per-episode counter
            fwd = np.array([np.cos(yaw), np.sin(yaw)])
            side = np.array([-fwd[1], fwd[0]])
            hip = src.TRI[fr][:, [11, 12]]
            hv = src.VAL[fr][:, [11, 12]]
            hip_f = (hip[..., :2] @ fwd)[hv]
            o_f = T[:, :2, 3] @ fwd
            o_s = T[:, :2, 3] @ side
            near = max(float(o_f.min()) - PAD, float(np.max(hip_f)) + TORSO_HALF if len(hip_f) else -1e9)
            near = min(near, float(o_f.min()) - 0.03)   # keep a surface under the product
            far = float(o_f.max()) + PAD
            s0, s1_ = float(o_s.min()) - PAD, float(o_s.max()) + PAD
            cen = fwd * (near + far) / 2 + side * (s0 + s1_) / 2
            counter = dict(center=cen.tolist(), size=[far - near, s1_ - s0], yaw=yaw)
        else:
            counter = CB_
        hold = [dict(hand=h["hand"], start=int(np.searchsorted(TM, int(h["start"]) - 1e-6)),
                     end=int(np.searchsorted(TM, int(h["end_excl"]) - 1e-6)))
                for h in src.holding.get(jid, {}).get("holding_segments", [])]   # source frames -> output steps
        trk = {}
        if attach:
            T1 = T.copy()
            T, car = OA.attach(T1, hold, {sd: ik["%s|%s__hand_T" % (jid, sd)] for sd in ("left", "right")},
                               {sd: ik["%s|%s__target_T" % (jid, sd)] for sd in ("left", "right")}, pm["dims"], settle_n)
            hs = car >= 0
            cyl = pm["dims"]["shape"] != "box"
            dv = np.linalg.norm(T[:, :3, 3] - T1[:, :3, 3], axis=1)
            dr = np.array([_ang(T[t, :3, :3], T1[t, :3, :3], cyl) for t in range(n)])
            arr[jid + "|obj_T_s1"] = T1.astype(np.float32)
            arr[jid + "|obj_dev"] = np.where(hs, dv, np.nan).astype(np.float32)
            arr[jid + "|obj_carrier"] = car.astype(np.int8)
            aft = [t for t in range(n) if car[t] < 0 and t > 0 and car[:t].max() >= 0]
            trk = dict(hold_dev_p50_mm=round(1e3 * float(np.median(dv[hs])), 1) if hs.any() else None,
                       hold_dev_p90_mm=round(1e3 * float(np.percentile(dv[hs], 90)), 1) if hs.any() else None,
                       hold_dev_max_mm=round(1e3 * float(dv[hs].max()), 1) if hs.any() else None,
                       hold_rot_max_deg=round(float(dr[hs].max()), 1) if hs.any() else None,
                       place_dev_mm=round(1e3 * float(dv[aft[-1]]), 1) if aft else None)
        arr[jid + "|obj_T"] = T.astype(np.float32)
        arr[jid + "|obj_ok"] = okT
        eps[jid] = dict(dims=pm["dims"], product=o.product, mesh=o.mesh, mesh_perm=pm["mesh_perm"], holding=hold,
                        counter=counter, track=trk)
    np.savez_compressed(out_prefix + ".npz", **arr)
    info = src.ds.info
    js = dict(kind="ARCADE FFW-SH5 product trajectory (output steps)", attach=bool(attach),
              ik=os.path.basename(ik_prefix) + ".npz",
              release=dict(name=info.get("name"), version=info.get("release_version"), session=info.get("session")),
              episodes=eps)
    json.dump(js, open(out_prefix + ".json", "w"), indent=1)
    print("OBJ_EXPORT_DONE", out_prefix, len(eps), "/", len(all_j), flush=True)
    return js


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="ARCADE-Checkout-Human release root")
    ap.add_argument("--ik", required=True, help="retargeting output prefix of the ik archive (without .npz)")
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--attach", type=int, default=1, help="attach the held product to the robot hand (0: keep the human product path)")
    ap.add_argument("--settle_n", type=int, default=5, help="steps over which a released product settles onto a stable face")
    a = ap.parse_args()
    export(a.release, a.ik, a.out, bool(a.attach), a.settle_n)


if __name__ == "__main__":
    main()
