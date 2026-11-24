"""Command line: arcade-human {info,validate,quality,view,video,still,grid,products,overview} ..."""
from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="arcade-human", description="Read, check and visualise an ARCADE-Checkout-Human release.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="print a dataset summary")
    p.add_argument("root")
    p = sub.add_parser("validate", help="check a release against the schema and physical sanity checks")
    p.add_argument("root")
    p.add_argument("--no-physical", action="store_true", help="skip physical sanity checks")
    p = sub.add_parser("quality", help="quality summary: the README numbers, computed from the files")
    p.add_argument("root"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("view", help="interactive 3-D viewer (rerun; extra: viewer)")
    p.add_argument("root"); p.add_argument("episode")
    p.add_argument("--save", default=None, help="write an .rrd recording instead of opening the viewer")
    p.add_argument("--masks", action="store_true", help="also log the product mask of the top camera")
    p = sub.add_parser("video", help="studio-rendered episode video with timeline (MP4 + optional WebP; extra: render)")
    p.add_argument("root"); p.add_argument("episodes", help="comma-separated episode ids"); p.add_argument("out")
    p.add_argument("--webp", default=None, help="also write an animated WebP (for READMEs)")
    p.add_argument("--width", type=int, default=1920); p.add_argument("--height", type=int, default=1080)
    p.add_argument("--layout", choices=("hero", "scene"), default="hero",
                   help="hero: scene + hands close-up (default); scene: the scene only")
    p = sub.add_parser("still", help="studio-rendered single frame (PNG; extra: render)")
    p.add_argument("root"); p.add_argument("episode"); p.add_argument("out")
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--layout", choices=("hero", "scene"), default="hero")
    p = sub.add_parser("grid", help="mosaic of several episodes playing at once (MP4 + optional WebP; extra: render)")
    p.add_argument("root"); p.add_argument("episodes", help="comma-separated episode ids"); p.add_argument("out")
    p.add_argument("--webp", default=None); p.add_argument("--cols", type=int, default=3)
    p.add_argument("--seconds", type=float, default=8.0, help="clip length; each episode is resampled to it")
    p = sub.add_parser("products", help="product gallery (PNG; extra: render)")
    p.add_argument("root"); p.add_argument("out")
    p = sub.add_parser("overview", help="trajectory / event timeline plot (PNG; extra: viz)")
    p.add_argument("root"); p.add_argument("episode"); p.add_argument("out")
    a = ap.parse_args(argv)

    if a.cmd == "info":
        from .reader import ArcadeHuman
        i = ArcadeHuman(a.root).info
        print(json.dumps({k: i[k] for k in ("name", "release_version", "schema", "session", "fps", "n_episodes",
                                             "n_frames", "n_events", "n_mask_files", "products") if k in i}, indent=1))
        return 0
    if a.cmd == "validate":
        from .validate import validate
        errors, warns = validate(a.root, physical=not a.no_physical)
        for w in warns:
            print("WARN ", w)
        for e in errors:
            print("ERROR", e)
        print(f"{len(errors)} error(s), {len(warns)} warning(s)")
        return 1 if errors else 0
    if a.cmd == "quality":
        from .quality import main as quality
        print(quality(a.root, a.json))
        return 0
    if a.cmd == "view":
        from .viewer import view
        print(view(a.root, a.episode, a.save, a.masks) or "viewer launched")
        return 0
    if a.cmd in ("video", "still", "grid", "products"):
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            os.environ.setdefault("MUJOCO_GL", "egl")          # headless Linux; macOS/Windows use the default
        try:
            import mujoco  # noqa: F401
        except ImportError:
            raise SystemExit('rendering needs the render extra: pip install -e ".[render]"')
        from . import render as R
        if a.cmd == "video":
            print(R.render_episode_video(a.root, a.episodes.split(","), a.out, a.webp, a.width, a.height, a.layout))
        elif a.cmd == "still":
            print(R.render_still(a.root, a.episode, a.out, a.frame, layout=a.layout))
        elif a.cmd == "grid":
            print(R.render_grid(a.root, a.episodes.split(","), a.out, cols=a.cols, seconds=a.seconds, webp=a.webp))
        else:
            print(R.render_products(a.root, a.out))
        return 0
    from .reader import ArcadeHuman
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        raise SystemExit('the episode card needs the viz extra: pip install -e ".[viz]"')
    from .viz import plot_overview
    print(plot_overview(ArcadeHuman(a.root).load(a.episode), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
