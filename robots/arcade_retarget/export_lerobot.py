"""Retargeting outputs (FFW-SH5, two UR10e + 2F-140 or Unitree G1 + Dex3-1) -> LeRobot dataset (codebase v2.1, state-only).

  python -m arcade_retarget.export_lerobot --retarget build/ffw_sh5 --release ARCADE_HUMAN --out build/lerobot_ffw_sh5
  python -m arcade_retarget.export_lerobot --retarget build/ur10e_2f140 --release ARCADE_HUMAN --out build/lerobot_ur10e_2f140
  python -m arcade_retarget.export_lerobot --retarget build/g1_dex3 --release ARCADE_HUMAN --out build/lerobot_g1_dex3

The robot is read from PREFIX_ik.json ("robot"; files without it are FFW-SH5).

For lerobot >= 0.4 (codebase v3.0), convert the result with lerobot's own converter:

  python -m lerobot.scripts.convert_dataset_v21_to_v30 --repo-id=local/arcade_ffw_sh5 \\
      --root=build/lerobot_ffw_sh5 --push-to-hub=false

Per frame (one row per retargeted output step; the steps follow the capture clock, 19.94 Hz,
and are stamped at a nominal 20 Hz because LeRobot needs an integer rate):
  observation.state             float32[60]  FFW-SH5 joint positions (names in meta/info.json)
                                float32[14]  UR10e: 2 x 6 arm joints + 2 x finger_joint of the 2F-140 grippers
                                float32[50]  G1: 43 joints (legs, waist, arms, Dex3-1 hands) + pelvis pose [x,y,z,qx,qy,qz,qw]
  action                        same size    joint position target = next step's position
                                             (the last step holds its position)
  observation.environment_state float32[9]   product pose [x,y,z,qx,qy,qz,qw] + which hand carries it (left, right);
                                             UR10e, G1: which gripper / hand holds it (both during a hand-over)
  source_frame                  float32[1]   the ARCADE-Checkout-Human session frame this step shows (fractional
                                             where the robot was slowed down); links to the human data
  timestamp, frame_index, episode_index, index, task_index, next.done

--release is an ARCADE-Checkout-Human release of the same session. With it, meta/info.json "splits" holds
the leakage-free time blocks of arcade_human.splits.time_split, meta/splits.json lists them by episode,
and (FFW-SH5) the task sentences come from the human data; UR10e and G1 task sentences always come from
the robot's own grasps. Without it every episode is put in "train" (no time split, no meta/splits.json)
and a warning is printed.

Frames: base x/y/yaw, product pose and everything else are in the robot world frame: the
counter frame of ARCADE-Checkout-Human shifted up by counter_h, so the floor is z = 0 and the counter
top is z = counter_h (0.80 m by default). The UR10e bases are fixed (meta/arcade.json "bases"); the G1
pelvis pose is part of the state.
There is no video in this version.
Requires pyarrow.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import warnings
from typing import Dict, List

import numpy as np

CODEBASE_VERSION = "v2.1"
CHUNK_SIZE = 1000
ARM = [f"arm_{s}_joint{i}" for s in ("l", "r") for i in range(1, 8)]
FINGERS = [f"finger_{s}_joint{i}" for s in ("l", "r") for i in range(1, 21)]
HEAD = ["head_joint1", "head_joint2"]
LIFT = ["lift_joint"]             # held at its neutral position (0) by the retargeting
BASE = ["base_x", "base_y", "base_yaw"]
STATE_NAMES = ARM + FINGERS + HEAD + LIFT + BASE
ENV_NAMES = ["product_x", "product_y", "product_z", "product_qx", "product_qy", "product_qz", "product_qw",
             "left_carrying", "right_carrying"]
FPS = 20                          # nominal LeRobot rate (integer); the capture runs at 19.94 Hz
ROBOT_TYPE = "ffw_sh5_rev1"       # ROBOTIS naming (URDF ffw_sh5_rev1_follower)
GROUPS = (("left_arm", 7), ("right_arm", 7), ("left_hand", 20), ("right_hand", 20), ("head", 2), ("lift", 1), ("base", 3))
UR_GROUPS = (("left_arm", 6), ("right_arm", 6), ("left_gripper", 1), ("right_gripper", 1))
ROBOT_NAMES = {"ffw_sh5": "FFW-SH5", "ur10e_2f140": "UR10e + Robotiq 2F-140", "g1_dex3": "Unitree G1 + Dex3-1"}


def _quat_xyzw(R: np.ndarray) -> np.ndarray:
    from scipy.spatial.transform import Rotation
    q = Rotation.from_matrix(R).as_quat()          # xyzw
    q[q[:, 3] < 0] *= -1
    return q


def task_of(ep: Dict) -> str:
    """Language task of a retargeted episode from its holding intervals: which hand picks the product
    up, whether both hands hold it, and which hand puts it down (``arcade_human.tasks``)."""
    from arcade_human.tasks import task_sentence
    hold = ep["holding"]
    if not hold:
        return task_sentence(ep["dims"]["shape"], "right", "right", False)
    first = min(hold, key=lambda h: h["start"])["hand"]          # earliest grasp (first listed on a tie)
    last = hold[0]
    for h in hold:                                               # latest release (last listed on a tie)
        if h["end"] >= last["end"]:
            last = h
    return task_sentence(ep["dims"]["shape"], first, last["hand"], len({h["hand"] for h in hold}) > 1)


def _stats(x: np.ndarray) -> Dict:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    return dict(min=x.min(0).tolist(), max=x.max(0).tolist(), mean=x.mean(0).tolist(),
                std=x.std(0).tolist(), count=[int(len(x))])


def export(retarget_prefix: str, out: str, episodes: List[str] = None, overwrite: bool = False,
           fps: int = FPS, release: str = None) -> Dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from arcade_retarget import g1_dex3 as g1
    from arcade_retarget import ur10e_2f140 as ur
    ik_meta = json.load(open(retarget_prefix + "_ik.json"))
    robot = ik_meta.get("robot", "ffw_sh5")
    if robot not in ("ffw_sh5", ur.ROBOT, g1.ROBOT):
        raise SystemExit(f"unknown robot {robot!r} in {retarget_prefix}_ik.json")
    is_ur, is_g1 = robot == ur.ROBOT, robot == g1.ROBOT
    state_names, layout = ((ur.STATE_NAMES, UR_GROUPS) if is_ur else (g1.STATE_NAMES, g1.GROUPS) if is_g1
                           else (STATE_NAMES, GROUPS))
    ik = np.load(retarget_prefix + "_ik.npz", allow_pickle=False)
    hd = None if is_ur or is_g1 else np.load(retarget_prefix + "_hand.npz", allow_pickle=False)
    ob = np.load(retarget_prefix + "_obj.npz", allow_pickle=False)
    ob_meta = json.load(open(retarget_prefix + "_obj.json"))
    counter_h = float(ik_meta.get("counter_h", 0.8))
    capture_fps = float(ik_meta.get("args", {}).get("fps", 19.94))
    jids = sorted(k.split("|")[0] for k in ik.files if k.endswith("|frames"))
    jids = [j for j in jids if j in ob_meta["episodes"] and (not episodes or j in episodes)]

    if os.path.exists(out):
        if not overwrite:
            raise SystemExit(f"{out} exists (use --overwrite)")
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "meta"))

    human_eps = None
    if not release:
        warnings.warn("no --release given: every episode goes to the 'train' split and meta/splits.json is not "
                      "written. Pass the ARCADE-Checkout-Human release the retargeting came from to get the time splits.",
                      stacklevel=2)
    if release and not (is_ur or is_g1):          # the task sentence of the human data (core handling)
        from arcade_human import ArcadeHuman
        _ds = ArcadeHuman(release)
        human_eps = {e: _ds.load(e) for e in jids if e in _ds.episode_ids}
    tasks: Dict[str, int] = {}
    ep_rows, stat_rows, index0 = [], [], 0
    all_state, all_action, all_env = [], [], []
    for ei, jid in enumerate(jids):
        if is_ur:
            assert list(ik[jid + "|joint_names"]) == ur.JOINT_NAMES, jid
            q = ik[jid + "|q"].astype(np.float32)                                  # (n, 12)
            n = len(q)
            state = np.concatenate([q, ik[jid + "|gripper"]], axis=1).astype(np.float32)
        elif is_g1:
            assert list(ik[jid + "|joint_names"]) == g1.JOINT_NAMES, jid
            q = ik[jid + "|q"].astype(np.float32)                                  # (n, 43)
            n = len(q)
            pelvis = ik[jid + "|pelvis"].astype(np.float32).copy()                 # counter frame -> robot world
            pelvis[:, 2] += counter_h
            state = np.concatenate([q, pelvis], axis=1).astype(np.float32)
        else:
            assert list(ik[jid + "|joint_names"]) == ARM, jid
            q = ik[jid + "|q"].astype(np.float32)                                  # (n, 14)
            fl, fr = hd[jid + "|left__fingers"], hd[jid + "|right__fingers"]       # (n, 20) each
            head = ik[jid + "|head"].astype(np.float32)                            # (n, 2)
            base = ik[jid + "|base_traj"][:, :3].astype(np.float32)                # x, y, yaw
            n = len(q)
            lift = ik[jid + "|base_traj"][:, 3:4].astype(np.float32)               # held at 0 by the retargeting
            state = np.concatenate([q, fl, fr, head, lift, base], axis=1).astype(np.float32)
        assert state.shape == (n, len(state_names)), (jid, state.shape)
        action = np.concatenate([state[1:], state[-1:]], axis=0)
        T = ob[jid + "|obj_T"].astype(np.float64)
        pos = T[:, :3, 3] + np.array([0.0, 0.0, counter_h])
        hold = np.zeros((n, 2), np.float32)
        epm = ob_meta["episodes"][jid]
        if is_ur or is_g1:                                                         # grippers / hands holding the product
            hold[:] = ob[jid + "|obj_holding"]
        elif jid + "|obj_carrier" in ob.files:                                    # the hand the product rides with
            car = ob[jid + "|obj_carrier"]
            hold[:, 0], hold[:, 1] = car == 0, car == 1
        else:
            for h in epm["holding"]:
                hold[h["start"]:h["end"], 0 if h["hand"] == "left" else 1] = 1.0
        env = np.concatenate([pos, _quat_xyzw(T[:, :3, :3]), hold], axis=1).astype(np.float32)
        if is_ur:
            task = ur.task_sentence(epm["dims"]["shape"], epm["holding"])
        elif is_g1:
            task = g1.task_sentence(epm["dims"]["shape"], epm["holding"])
        else:
            task = human_eps[jid].task if human_eps is not None and jid in human_eps else task_of(epm)
        ti = tasks.setdefault(task, len(tasks))

        ts = (np.arange(n) / fps).astype(np.float32)
        src = ik[jid + "|tmap"].astype(np.float32)
        table = pa.table({
            "observation.state": pa.array(list(state), type=pa.list_(pa.float32())),
            "action": pa.array(list(action), type=pa.list_(pa.float32())),
            "observation.environment_state": pa.array(list(env), type=pa.list_(pa.float32())),
            "source_frame": pa.array(src, type=pa.float32()),
            "timestamp": pa.array(ts, type=pa.float32()),
            "frame_index": pa.array(np.arange(n), type=pa.int64()),
            "episode_index": pa.array(np.full(n, ei), type=pa.int64()),
            "index": pa.array(index0 + np.arange(n), type=pa.int64()),
            "task_index": pa.array(np.full(n, ti), type=pa.int64()),
            "next.done": pa.array(np.arange(n) == n - 1, type=pa.bool_()),
        })
        chunk = ei // CHUNK_SIZE
        d = os.path.join(out, "data", f"chunk-{chunk:03d}")
        os.makedirs(d, exist_ok=True)
        pq.write_table(table, os.path.join(d, f"episode_{ei:06d}.parquet"))

        ep_rows.append(dict(episode_index=ei, tasks=[task], length=n, source_episode_id=jid,
                            product=epm["product"], source_frames=[int(ik[jid + "|frames"][0]), int(ik[jid + "|frames"][-1])]))
        if is_g1:                                                                  # the physics replay kept the product in every hold
            ep_rows[-1]["physics_all_held"] = bool(epm["physics"]["all_held"])
        stat_rows.append(dict(episode_index=ei, stats={
            "observation.state": _stats(state), "action": _stats(action), "observation.environment_state": _stats(env),
            "source_frame": _stats(src), "timestamp": _stats(ts), "frame_index": _stats(np.arange(n)), "episode_index": _stats(np.full(n, ei)),
            "index": _stats(index0 + np.arange(n)), "task_index": _stats(np.full(n, ti)),
            "next.done": _stats((np.arange(n) == n - 1).astype(np.float64)),
        }))
        all_state.append(state); all_action.append(action); all_env.append(env)
        index0 += n

    def vec(names):
        return dict(dtype="float32", shape=[len(names)], names=names)

    features = {
        "observation.state": vec(state_names),
        "action": vec(state_names),
        "observation.environment_state": vec(ENV_NAMES),
        "source_frame": dict(dtype="float32", shape=[1], names=None),
        "timestamp": dict(dtype="float32", shape=[1], names=None),
        "frame_index": dict(dtype="int64", shape=[1], names=None),
        "episode_index": dict(dtype="int64", shape=[1], names=None),
        "index": dict(dtype="int64", shape=[1], names=None),
        "task_index": dict(dtype="int64", shape=[1], names=None),
        "next.done": dict(dtype="bool", shape=[1], names=None),
    }
    splits = {"train": f"0:{len(ep_rows)}"}
    split_lists = None
    if release:
        from arcade_human import ArcadeHuman
        from arcade_human.splits import time_split
        idx = {r["source_episode_id"]: r["episode_index"] for r in ep_rows}
        ts_ = time_split(ArcadeHuman(release))
        split_lists = {k: sorted(idx[e] for e in v if e in idx) for k, v in ts_.items()}
        if not any(split_lists.values()):
            warnings.warn("none of the exported episodes is in the --release given: every episode goes to the "
                          "'train' split and meta/splits.json is not written. Pass the full ARCADE-Checkout-Human release.",
                          stacklevel=2)
            split_lists = None
        else:
            splits = {}
            for k in ("train", "val", "test"):
                v = split_lists.get(k, [])
                if v:
                    assert v == list(range(v[0], v[-1] + 1)), f"{k} split is not contiguous"
                    splits[k] = f"{v[0]}:{v[-1] + 1}"
    info = dict(
        codebase_version=CODEBASE_VERSION, robot_type=ur.ROBOT_TYPE if is_ur else g1.ROBOT_TYPE if is_g1 else ROBOT_TYPE,
        total_episodes=len(ep_rows), total_frames=index0,
        total_tasks=len(tasks), total_videos=0, total_chunks=(len(ep_rows) - 1) // CHUNK_SIZE + 1 if ep_rows else 0,
        chunks_size=CHUNK_SIZE, fps=int(fps), splits=splits,
        data_path="data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet", video_path=None,
        features=features,
    )
    json.dump(info, open(os.path.join(out, "meta", "info.json"), "w"), indent=4)
    with open(os.path.join(out, "meta", "tasks.jsonl"), "w") as f:
        for t, i in sorted(tasks.items(), key=lambda kv: kv[1]):
            f.write(json.dumps(dict(task_index=i, task=t)) + "\n")
    with open(os.path.join(out, "meta", "episodes.jsonl"), "w") as f:
        for r in ep_rows:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(out, "meta", "episodes_stats.jsonl"), "w") as f:
        for r in stat_rows:
            f.write(json.dumps(r) + "\n")
    if ep_rows:   # aggregate stats (meta/stats.json, read by v2.0-era tools)
        S, A_, E = (np.concatenate(x) for x in (all_state, all_action, all_env))
        json.dump({"observation.state": _stats(S), "action": _stats(A_), "observation.environment_state": _stats(E)},
                  open(os.path.join(out, "meta", "stats.json"), "w"), indent=1)
    # slice map for GR00T-style loaders (state/action layout)
    o = 0
    groups = {}
    for name, k in layout:
        groups[name] = dict(start=o, end=o + k)
        o += k
    state = dict(groups)
    state["product_pose"] = dict(original_key="observation.environment_state", start=0, end=7)
    state["carrying"] = dict(original_key="observation.environment_state", start=7, end=9)
    json.dump(dict(state=state, action=groups,
                   annotation={"human.task_description": dict(original_key="task_index")}),
              open(os.path.join(out, "meta", "modality.json"), "w"), indent=1)
    if split_lists is not None:
        json.dump(dict(split_lists, note="time blocks of arcade_human.splits.time_split: no session frame is shared "
                                         "between train, val and test; boundary episodes belong to none of them"),
                  open(os.path.join(out, "meta", "splits.json"), "w"), indent=1)
    from arcade_retarget import __version__
    prov = dict(source=f"ARCADE {ROBOT_NAMES[robot]} retargeting",
                version=__version__, counter_h=counter_h,
                frame="robot world: floor z = 0", capture_fps=capture_fps, fps=int(fps),
                timing=f"one row per retargeted step; steps follow the {capture_fps:.2f} Hz capture clock and "
                       f"are stamped at a nominal {int(fps)} Hz",
                retarget=ik_meta.get("release") or ik_meta.get("source"), counter=ik_meta.get("counter"))
    if is_ur:
        prov.update(bases=ik_meta.get("bases"), mount=ik_meta.get("mount"))
    if is_g1:
        prov.update(pelvis="observation.state 43-49: pelvis position (robot world) and orientation quaternion xyzw",
                    physics=ik_meta.get("physics"))
    json.dump(prov, open(os.path.join(out, "meta", "arcade.json"), "w"), indent=1)
    print(f"LeRobot {CODEBASE_VERSION}: {len(ep_rows)} episodes, {index0} frames, {len(tasks)} tasks -> {out}")
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--retarget", required=True, help="retarget output prefix (as given to --out of the retargeting)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--episodes", default="")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--fps", type=int, default=FPS, help="integer frame rate written to the dataset")
    ap.add_argument("--release", default=None, help="ARCADE-Checkout-Human release the retargeting came from: leakage-free time splits and the "
                    "task sentences of the human data. Without it every episode is put in the train split")
    a = ap.parse_args()
    export(a.retarget, a.out, [e for e in a.episodes.split(",") if e] or None, a.overwrite, a.fps, a.release)


if __name__ == "__main__":
    main()
