"""Interactive 3-D viewer for ARCADE-Checkout-Human episodes, built on rerun (https://rerun.io).

    pip install "arcade-human[viewer]"                      # rerun-sdk >= 0.28 (use its own venv next to lerobot 0.3)
    arcade-human view RELEASE J03826_left                   # opens the rerun viewer
    arcade-human view RELEASE J03826_left --save ep.rrd     # or write a recording: `rerun ep.rrd` on any machine

Logged per frame on the ``frame`` timeline (and ``time`` in seconds):
  world/body          upper-body skeleton (line strips + joints)
  world/hands/<side>  21 hand landmarks + bones, coloured per hand
  world/wrist/<side>  wrist SE(3) axes
  world/product       textured product mesh, posed by the 6-DoF trajectory
  holding/<side>      1 while that hand holds the product (time series)
  events              grasp / release text events
  masks/<view>        the product's segmentation mask per camera (optional, --masks)
Everything is in the counter frame (z up, counter top at z = 0).
"""
from __future__ import annotations

import argparse
import os
from typing import Optional

import numpy as np

from . import schema as S
from .reader import ArcadeHuman

from .style import body_rgb255, hex_rgb255, PALETTE, side_rgb255

UPPER_BODY = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (3, 4)]
SIDE_RGB = {s: side_rgb255(s) for s in ("left", "right")}
BODY_RGB = body_rgb255()
MIN_RERUN = (0, 28)


def _rerun():
    try:
        import rerun as rr
    except ImportError:
        raise SystemExit('the viewer needs rerun: pip install -e ".[viewer]"')
    ver = tuple(int(x) for x in rr.__version__.split(".")[:2])
    if ver < MIN_RERUN:
        raise SystemExit(f"the viewer needs rerun-sdk >= {MIN_RERUN[0]}.{MIN_RERUN[1]} (found {rr.__version__}); "
                         "lerobot 0.3.x pins an older rerun, so use a separate environment")
    return rr


def log_episode(ds: ArcadeHuman, episode_id: str, masks: bool = False, mask_views=("top",), stride: int = 1):
    from .render import CAPTURE_COUNTER as C
    rr = _rerun()

    ep = ds.load(episode_id)
    fps = float(ep.attrs.get("fps", 19.94))
    rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)
    rr.log("world/counter_top", rr.Boxes3D(centers=[[(C["x0"] + C["x1"]) / 2, (C["y0"] + C["y1"]) / 2, -0.01]],
                                           half_sizes=[[(C["x1"] - C["x0"]) / 2, (C["y1"] - C["y0"]) / 2, 0.01]],
                                           colors=[hex_rgb255(PALETTE["counter_top"])], fill_mode="solid"), static=True)
    mesh = ep.product_mesh_path
    rr.log("world/product/mesh", rr.Asset3D(path=mesh), static=True)
    rr.log("holding/left", rr.SeriesLines(colors=[SIDE_RGB["left"]], names=["left hand"]), static=True)
    rr.log("holding/right", rr.SeriesLines(colors=[SIDE_RGB["right"]], names=["right hand"]), static=True)
    ev_by_frame = {}
    for e in ep.events:
        ev_by_frame.setdefault(e["frame"], []).append(f"{e['kind']} ({e['hand']})")
    T = ep.object_matrix()
    for k in range(0, len(ep), stride):
        rr.set_time("frame", sequence=int(k))
        rr.set_time("time", duration=float(k / fps))
        b = ep.body_position[k]
        strips = [b[[i, j]] for i, j in UPPER_BODY if np.isfinite(b[[i, j]]).all()]
        rr.log("world/body", rr.LineStrips3D(strips, colors=BODY_RGB, radii=0.012))
        pts = b[:13][np.isfinite(b[:13]).all(axis=1)]
        rr.log("world/body/joints", rr.Points3D(pts, colors=BODY_RGB, radii=0.02))
        for side in S.SIDES:
            h = ep.hand_position(side)[k]
            bones = [h[[i, j]] for i, j in S.HAND_CONNECTIONS if np.isfinite(h[[i, j]]).all()]
            rr.log(f"world/hands/{side}", rr.LineStrips3D(bones, colors=SIDE_RGB[side], radii=0.003))
            rr.log(f"world/hands/{side}/landmarks", rr.Points3D(h[np.isfinite(h).all(axis=1)], colors=SIDE_RGB[side], radii=0.005))
            if ep[f"wrist/{side}/valid"][k]:
                W = ep.wrist_matrix(side)[k]
                rr.log(f"world/wrist/{side}", rr.Transform3D(translation=W[:3, 3], mat3x3=W[:3, :3]),
                       rr.TransformAxes3D(axis_length=0.06))
            rr.log(f"holding/{side}", rr.Scalars(float(ep[f"interaction/{side}/holding"][k])))
        if ep["object/valid"][k]:
            rr.log("world/product", rr.Transform3D(translation=T[k, :3, 3], mat3x3=T[k, :3, :3]))
        if k in ev_by_frame:
            rr.log("events", rr.TextLog(", ".join(ev_by_frame[k]), level="INFO"))
        if masks:
            for v in mask_views:
                m = ds.product_mask(episode_id, v, k)
                if m is not None:
                    rr.log(f"masks/{v}", rr.SegmentationImage(m.astype(np.uint8)))
    return ep


def blueprint():
    import rerun.blueprint as rrb
    return rrb.Blueprint(
        rrb.Vertical(
            rrb.Spatial3DView(origin="world", name="3-D (counter frame)"),
            rrb.Horizontal(rrb.TimeSeriesView(origin="holding", name="holding per hand"),
                           rrb.TextLogView(origin="events", name="events")),
            row_shares=[3, 1]),
        collapse_panels=True)


def view(root: str, episode_id: str, save: Optional[str] = None, masks: bool = False, stride: int = 1):
    import sys
    rr = _rerun()
    ds = ArcadeHuman(root)
    if episode_id not in ds.episode_ids:
        raise SystemExit(f"unknown episode {episode_id!r}; this release has {', '.join(ds.episode_ids[:5])}"
                         + (", ..." if len(ds) > 5 else ""))
    if save is None and sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        save = f"{episode_id}.rrd"
        print(f"no display found: writing {save} instead; open it with `rerun {save}` on a machine with a screen")
    rr.init(f"arcade_human_{episode_id}", spawn=save is None)
    if save:
        rr.save(save, default_blueprint=blueprint())
    else:
        rr.send_blueprint(blueprint())
    log_episode(ds, episode_id, masks=masks, stride=stride)
    return save


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m arcade_human.viewer", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root"); ap.add_argument("episode")
    ap.add_argument("--save", default=None, help="write an .rrd recording instead of opening the viewer")
    ap.add_argument("--masks", action="store_true", help="also log the product mask of the top camera")
    ap.add_argument("--stride", type=int, default=1)
    a = ap.parse_args(argv)
    print(view(a.root, a.episode, a.save, a.masks, a.stride) or "viewer launched")


if __name__ == "__main__":
    main()
