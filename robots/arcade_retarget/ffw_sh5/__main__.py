"""Retarget an ARCADE-Checkout-Human release to FFW-SH5: shard episodes over processes, merge, export products.

  python -m arcade_retarget.ffw_sh5 --release REL --out build/ffw_sh5 [--episodes a,b] [--workers 8]

Writes <out>_ik.npz/.json/.log, <out>_hand.npz/.json and <out>_obj.npz/.json (docs/FORMAT.md).
Extra arguments after ``--`` are passed to the solver (arcade_retarget.ffw_sh5.solver).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

from arcade_retarget.ffw_sh5.object_track import export as export_objects


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="python -m arcade_retarget.ffw_sh5", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="ARCADE-Checkout-Human release root")
    ap.add_argument("--out", required=True, help="output prefix, e.g. build/ffw_sh5")
    ap.add_argument("--episodes", default="", help="comma-separated episode ids (default: all)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--counter", default="auto")
    ap.add_argument("--urdf", default=None)
    ap.add_argument("--mesh-root", default=None)
    a = ap.parse_args(argv)
    try:
        import pinocchio  # noqa: F401
        import pink  # noqa: F401
    except ImportError:
        sys.exit('the solver needs the solver extra: pip install -e ".[solver]"')
    import scipy
    if tuple(int(x) for x in scipy.__version__.split(".")[:2]) < (1, 16):
        sys.exit(f"the solver needs SciPy >= 1.16 (Python >= 3.11); found {scipy.__version__}")

    rows = [json.loads(l) for l in open(os.path.join(a.release, "meta", "episodes.jsonl")) if l.strip()]
    eps = sorted(r["episode_id"] for r in rows)
    if a.episodes:
        want = [e for e in a.episodes.split(",") if e]
        unknown = set(want) - set(eps)
        if unknown:
            sys.exit(f"unknown episodes: {sorted(unknown)}")
        eps = [e for e in eps if e in want]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    n = max(1, min(a.workers, len(eps)))
    ik, hd = a.out + "_ik", a.out + "_hand"
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    procs, t0 = [], time.time()
    for k in range(n):
        shard = eps[k::n]
        cmd = [sys.executable, "-m", "arcade_retarget.ffw_sh5.solver", "--release", a.release, "--jids", ",".join(shard),
               "--out_ik", f"{ik}_s{k}", "--out_hand", f"{hd}_s{k}", "--counter", a.counter]
        if a.urdf:
            cmd += ["--urdf", a.urdf]
        if a.mesh_root:
            cmd += ["--mesh_root", a.mesh_root]
        procs.append(subprocess.Popen(cmd + extra, stdout=open(f"{ik}_s{k}.log", "w"), stderr=subprocess.STDOUT, env=env))
    print(f"retargeting {len(eps)} episodes on {n} workers ...", flush=True)
    codes = [p.wait() for p in procs]
    if any(codes):
        sys.exit(f"worker failed (exit codes {codes}); see {ik}_s*.log")

    out = {ik: {}, hd: {}}
    meta, logs = {}, []
    for k in range(n):
        for t in (ik, hd):
            z = np.load(f"{t}_s{k}.npz", allow_pickle=False)
            out[t].update({x: z[x] for x in z.files})
            meta.setdefault(t, json.load(open(f"{t}_s{k}.json")))
        logs += [l for l in open(f"{ik}_s{k}.log") if l.startswith("J")]
    n_ep = len([x for x in out[ik] if x.endswith("|frames")])
    for t in (ik, hd):
        meta[t]["episodes"] = n_ep
        np.savez_compressed(t + ".npz", **out[t])
    meta[ik]["minutes"] = round((time.time() - t0) / 60, 1)
    meta[ik]["workers"] = n
    json.dump(meta[ik], open(ik + ".json", "w"), indent=1)
    json.dump(dict(meta[hd], ik=os.path.basename(ik) + ".npz"), open(hd + ".json", "w"), indent=1)
    with open(ik + ".log", "w") as f:
        f.writelines(sorted(logs) + [f"RETARGET_DONE {n_ep} episodes ({n} workers)\n"])
    for k in range(n):
        for suf in ("npz", "json", "log"):
            for t in (ik, hd):
                p = f"{t}_s{k}.{suf}"
                if os.path.exists(p):
                    os.remove(p)
    print(f"merged {n_ep} episodes -> {ik}.npz, {hd}.npz", flush=True)
    export_objects(a.release, ik, a.out + "_obj")
    return 0


if __name__ == "__main__":
    sys.exit(main())
