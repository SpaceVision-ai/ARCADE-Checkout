"""Read an ARCADE-Checkout-Human release.

    from arcade_human import ArcadeHuman
    ds = ArcadeHuman("path/to/release")
    ep = ds.load(ds.episode_ids[0])
    ep.hand_position("right")        # (T, 21, 3) float32, NaN where invalid
    ep.object_matrix()               # (T, 4, 4) product pose in the counter frame
    ep.events                        # [{'frame': 44, 'hand': 'left', 'kind': 'grasp'}, ...]
    ep.task                          # 'Pick up the bottle ... with the left hand, pass it to the right hand, ...'
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

import h5py
import numpy as np

from . import schema as S
from .geometry import load_obj_vertices, pose_to_matrix


def _attr(v):
    if isinstance(v, bytes):
        v = v.decode()
    if isinstance(v, str) and v[:1] in "[{" or v == "null":
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v
    if isinstance(v, np.generic):
        return v.item()
    return v


def list_mask_files(segmentation_dir: str) -> List[str]:
    """Mask files of one episode's segmentation folder, as ``<view>/<track_id>/<frame>.png``: from the
    unpacked ``masks/`` folder if there is one, else from ``masks.zip``."""
    d = os.path.join(segmentation_dir, "masks")
    if os.path.isdir(d):
        return sorted(os.path.relpath(os.path.join(dp, f), d).replace(os.sep, "/")
                      for dp, _, fs in os.walk(d) for f in fs if f.endswith(".png"))
    p = os.path.join(segmentation_dir, S.MASKS_ZIP)
    if not os.path.exists(p):
        return []
    with zipfile.ZipFile(p) as z:
        return sorted(n for n in z.namelist() if n.endswith(".png"))


@dataclass
class Episode:
    """One episode: per-frame arrays keyed by their HDF5 path, plus attributes."""

    episode_id: str
    attrs: Dict
    data: Dict[str, np.ndarray]
    root: str = ""
    _mesh_cache: Dict = field(default_factory=dict, repr=False)

    def __len__(self) -> int:
        return int(len(self.data["frame_index"]))

    def __getitem__(self, path: str) -> np.ndarray:
        return self.data[path]

    # -- convenience -------------------------------------------------------------------
    @property
    def n_frames(self) -> int:
        return len(self)

    @property
    def frame_index(self) -> np.ndarray:
        return self.data["frame_index"]

    @property
    def timestamp(self) -> np.ndarray:
        return self.data["timestamp"]

    @property
    def body_position(self) -> np.ndarray:
        return self.data["body/position"]

    def hand_position(self, side: str) -> np.ndarray:
        return self.data[f"hand/{side}/position"]

    def wrist_pose(self, side: str) -> np.ndarray:
        return self.data[f"wrist/{side}/pose"]

    def wrist_matrix(self, side: str) -> np.ndarray:
        return pose_to_matrix(self.data[f"wrist/{side}/pose"])

    @property
    def object_pose(self) -> np.ndarray:
        return self.data["object/pose"]

    def object_matrix(self) -> np.ndarray:
        return pose_to_matrix(self.data["object/pose"])

    @property
    def events(self) -> List[Dict]:
        return [dict(frame=int(f), session_frame=int(sf), hand=str(h), kind=str(k))
                for f, sf, h, k in zip(self.data["events/frame"], self.data["events/session_frame"],
                                       self.data["events/hand"], self.data["events/kind"])]

    def core_slice(self):
        """[start, end) of the core window in episode frames."""
        f0 = int(self.frame_index[0])
        cw = self.attrs.get("core_window") or [f0, f0 + len(self)]
        return max(int(cw[0]) - f0, 0), min(int(cw[1]) - f0, len(self))

    def handling(self):
        """(task kind, first hand, last hand) of the core handling; see ``arcade_human.tasks.core_handling``."""
        from .tasks import core_handling
        return core_handling({s: self.data[f"interaction/{s}/holding"] for s in S.SIDES}, self.core_slice())

    @property
    def task_kind(self) -> str:
        """'one_hand', 'pass' (ends in the other hand), 'both_hands' (both hold it, the first hand puts it
        down) or 'repeated' (put down and picked up again); see ``arcade_human.tasks``."""
        return self.handling()[0]

    @property
    def task(self) -> str:
        """The episode as one sentence, e.g. 'Pick up the bottle from the checkout counter with the left
        hand, pass it to the right hand, and put it down.'"""
        from .tasks import task_sentence
        kind, first, last = self.handling()
        return task_sentence(self.attrs.get("product_shape", ""), first, last, kind != "one_hand",
                             repeated=kind == "repeated")

    @property
    def product(self) -> str:
        return self.attrs["product"]

    @property
    def check_passed(self) -> bool:
        """The episode passes the automatic quality check (``schema.CHECK_RULES``)."""
        return bool(self.attrs.get("check_passed", True))

    @property
    def check_failed(self) -> List[str]:
        """Rule ids of the quality check the episode fails (empty when it passes)."""
        return list(self.attrs.get("check_failed") or [])

    @property
    def product_mesh_path(self) -> str:
        return os.path.join(self.root, self.attrs["product_mesh"])

    def product_mesh_vertices(self) -> np.ndarray:
        """Mesh vertices in the product frame (N, 3)."""
        p = self.product_mesh_path
        if p not in self._mesh_cache:
            self._mesh_cache[p] = load_obj_vertices(p)
        return self._mesh_cache[p]

    def object_vertices_world(self, t: int) -> Optional[np.ndarray]:
        """Product mesh vertices in the counter frame at frame t, or None if the pose is invalid."""
        if not self.data["object/valid"][t]:
            return None
        T = self.object_matrix()[t]
        return self.product_mesh_vertices() @ T[:3, :3].T + T[:3, 3]


class ArcadeHuman:
    """A release directory (see ``schema.RELEASE_FILES``)."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.info = json.load(open(os.path.join(self.root, "meta", "info.json")))
        self.index = [json.loads(l) for l in open(os.path.join(self.root, "meta", "episodes.jsonl")) if l.strip()]
        self.products = json.load(open(os.path.join(self.root, "meta", "products.json")))["products"]
        self.skeleton = json.load(open(os.path.join(self.root, "meta", "skeleton.json")))
        self.h5_path = os.path.join(self.root, "data", "human_motion.hdf5")
        self._by_id = {r["episode_id"]: r for r in self.index}
        self._zips: Dict[str, Optional[zipfile.ZipFile]] = {}

    def __len__(self) -> int:
        return len(self.index)

    def __iter__(self) -> Iterator[Episode]:
        for r in self.index:
            yield self.load(r["episode_id"])

    @property
    def episode_ids(self) -> List[str]:
        return [r["episode_id"] for r in self.index]

    @property
    def passed_ids(self) -> List[str]:
        """Episodes that pass the automatic quality check (``check_passed``)."""
        return [r["episode_id"] for r in self.index if r.get("check_passed", True)]

    def row(self, episode_id: str) -> Dict:
        return self._by_id[episode_id]

    def load(self, episode_id: str) -> Episode:
        with h5py.File(self.h5_path, "r") as f:
            g = f["episodes"][episode_id]
            data = {}
            for path in S.EPISODE_LAYOUT:
                if path not in g:          # optional entries
                    continue
                a = g[path][()]
                if a.dtype == object or a.dtype.kind in "SO":
                    a = np.array([x.decode() if isinstance(x, bytes) else str(x) for x in a], dtype=object)
                data[path] = a
            attrs = {k: _attr(v) for k, v in g.attrs.items()}
        return Episode(episode_id=episode_id, attrs=attrs, data=data, root=self.root)

    # -- segmentation ------------------------------------------------------------------
    def segmentation_meta(self, episode_id: str) -> Optional[Dict]:
        p = os.path.join(self.root, "segmentation", episode_id, "instances.json")
        return json.load(open(p)) if os.path.exists(p) else None

    def _masks_zip(self, episode_id: str) -> Optional[zipfile.ZipFile]:
        if episode_id not in self._zips:
            p = os.path.join(self.root, "segmentation", episode_id, S.MASKS_ZIP)
            self._zips[episode_id] = zipfile.ZipFile(p) if os.path.exists(p) else None
        return self._zips[episode_id]

    def mask_files(self, episode_id: str) -> List[str]:
        """Released mask files of an episode, as ``<view>/<track_id>/<frame>.png``."""
        return list_mask_files(os.path.join(self.root, "segmentation", episode_id))

    def masks(self, episode_id: str, view: str, frame: int) -> Dict[str, np.ndarray]:
        """All released masks of one view at an episode-relative frame: {track_id: bool (H, W)}.

        Reads ``segmentation/<episode_id>/masks.zip``, or the ``masks/`` folder if it was unpacked."""
        from PIL import Image
        name = "%05d.png" % frame
        d = os.path.join(self.root, "segmentation", episode_id, "masks", view)
        out = {}
        if os.path.isdir(d):
            for t in sorted(os.listdir(d)):
                p = os.path.join(d, t, name)
                if os.path.exists(p):
                    out[t] = np.array(Image.open(p)) > 127
            return out
        z = self._masks_zip(episode_id)
        if z is None:
            return out
        for n in sorted(z.namelist()):
            v, t, f = (n.split("/") + ["", "", ""])[:3]
            if v == view and f == name:
                out[t] = np.array(Image.open(io.BytesIO(z.read(n)))) > 127
        return out

    def product_mask(self, episode_id: str, view: str, frame: int) -> Optional[np.ndarray]:
        """Union of the episode product's (hero instance) tracks in one view, or None."""
        meta = self.segmentation_meta(episode_id)
        if not meta or not meta.get("hero_instance"):
            return None
        tracks = next((i["tracks"].get(view, []) for i in meta["instances"]
                       if i["instance_id"] == meta["hero_instance"]), [])
        ms = self.masks(episode_id, view, frame)
        sel = [ms[t] for t in tracks if t in ms]
        return np.any(sel, axis=0) if sel else None
