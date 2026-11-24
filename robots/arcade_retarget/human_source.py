"""ARCADE-Checkout-Human release -> the inputs the FFW-SH5 retargeting consumes.

The retargeting solver was written against session-level arrays: a 133-point whole-body
track indexed by session frame, per-episode holding segments and clip ranges, and per-episode
product poses. This module rebuilds exactly those structures from a public ARCADE-Checkout-Human
release, so the solver itself runs unchanged.

Everything is already in the ARCADE counter frame (z = 0 on the counter top), so the
canonical transform the solver applies is the identity and its counter datum is 0.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from arcade_human import ArcadeHuman
from arcade_human import schema as S
from arcade_human.geometry import pose_to_matrix

N_WHOLEBODY = 133


@dataclass
class EpisodeObject:
    frames: np.ndarray        # (n,) session frames
    T: np.ndarray             # (n, 4, 4) product pose in the counter frame, NaN where invalid
    state: np.ndarray         # (n,) object state (schema.OBJECT_STATES)
    dims: Dict                # {"shape": "cylinder"|"box", "r","h" | "l","w","h"}
    product: str
    mesh: str                 # mesh path relative to the ARCADE-Checkout-Human release root


class HumanSource:
    """Session-level view of an ARCADE-Checkout-Human release.

    Attributes mirror the names used by the retargeting code:
      TRI (F, 133, 3) float32 and VAL (F, 133) bool : whole-body points by session frame
      holding[episode]["holding_segments"]            : [{hand, start, end_excl}] (session frames): the hand
                                                        that carries the product (interaction/*/carrying),
                                                        or the holding intervals for releases without it
      clips[episode]                                  : {"session_frame0", "n"}
      OBJ[episode]                                    : EpisodeObject
    """

    def __init__(self, release_root: str, episodes: Optional[List[str]] = None):
        self.ds = ArcadeHuman(release_root)
        self.root = self.ds.root
        ids = self.ds.episode_ids if not episodes else [e for e in self.ds.episode_ids if e in set(episodes)]
        last = max(r["source_frame_range"][1] for r in self.ds.index)
        self.TRI = np.full((last + 1, N_WHOLEBODY, 3), np.nan, np.float32)
        self.VAL = np.zeros((last + 1, N_WHOLEBODY), bool)
        self.holding: Dict[str, Dict] = {}
        self.clips: Dict[str, Dict] = {}
        self.OBJ: Dict[str, EpisodeObject] = {}
        self.all_episode_ids = self.ds.episode_ids
        # the counter extent is a property of the whole session: always read every episode's product
        for eid in self.ds.episode_ids:
            ep = self.ds.load(eid)
            self.OBJ[eid] = EpisodeObject(
                frames=ep.frame_index.astype(np.int64), T=pose_to_matrix(ep.object_pose),
                state=ep["object/state"].astype(np.int64),
                dims=dict(shape=ep.attrs["product_shape"], **ep.attrs["product_dims"]),
                product=ep.product, mesh=ep.attrs["product_mesh"])
            if eid not in ids:
                continue
            fi = ep.frame_index.astype(np.int64)
            f0, n = int(fi[0]), len(fi)
            body_idx = list(S.BODY_SOURCE_INDICES)
            self.TRI[fi[:, None], body_idx] = ep.body_position
            self.VAL[fi[:, None], body_idx] = ep["body/valid"]
            segs = []
            for side in S.SIDES:
                idx = list(S.HAND_SOURCE_INDICES[side])
                self.TRI[fi[:, None], idx] = ep.hand_position(side)
                self.VAL[fi[:, None], idx] = ep[f"hand/{side}/valid"]
                key = f"interaction/{side}/carrying" if f"interaction/{side}/carrying" in ep.data else f"interaction/{side}/holding"
                h = ep[key].astype(np.int8)
                d = np.diff(np.r_[0, h, 0])
                for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
                    segs.append(dict(hand=side, start=f0 + int(a), end_excl=f0 + int(b)))
            self.holding[eid] = dict(holding_segments=sorted(segs, key=lambda s: (s["start"], s["hand"])),
                                events=ep.events)
            self.clips[eid] = dict(session_frame0=f0, n=n)

    def product_meta(self, episode_id: str) -> Dict:
        """dims, baked mesh file and axis permutation of an episode's product (for the distance field)."""
        o = self.OBJ[episode_id]
        perm = [int(c) for c in os.path.splitext(o.mesh)[0].rsplit("_p", 1)[-1]]
        return dict(dims=o.dims, mesh_file=os.path.join(self.root, o.mesh), mesh_perm=perm, mesh_product=o.product)

    @property
    def episode_ids(self) -> List[str]:
        return sorted(self.holding)

    def counter_box(self, near: float, far: float, side: float) -> Dict:
        """Counter extent over the whole session: the range of resting product centres, padded.
        Same rule as for the released data (objects not held: state not in {1, 2})."""
        X0, X1, Y0, Y1 = [], [], [], []
        for o in self.OBJ.values():
            ok = np.all(np.isfinite(o.T.reshape(len(o.T), -1)), 1) & ~np.isin(o.state, [1, 2])
            if ok.any():
                P = o.T[ok, :3, 3]
                X0.append(P[:, 0].min()); X1.append(P[:, 0].max()); Y0.append(P[:, 1].min()); Y1.append(P[:, 1].max())
        return dict(x0=float(min(X0) - near), x1=float(max(X1) + far), y0=float(min(Y0) - side),
                    y1=float(max(Y1) + side), yaw=0.0, top_z=0.0, n_episodes=len(X0))
