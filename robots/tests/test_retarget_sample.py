"""Checks on the shipped samples: raw retargeting outputs and the LeRobot exports (2 episodes)."""
import json
import os

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..", "samples")
RT = os.path.join(ROOT, "ffw_sh5_sample", "ffw_sh5")
LR21 = os.path.join(ROOT, "lerobot_ffw_sh5_v2.1")
LR30 = os.path.join(ROOT, "lerobot_ffw_sh5_v3.0")
HUMAN_SAMPLE = os.path.join(HERE, "..", "..", "human", "samples", "arcade_human_sample")


def test_retarget_outputs_consistent():
    ik = np.load(RT + "_ik.npz")
    hd = np.load(RT + "_hand.npz")
    ob = np.load(RT + "_obj.npz")
    jids = sorted(k.split("|")[0] for k in ik.files if k.endswith("|frames"))
    assert jids == ["J02562_right", "J03826_left"]
    for j in jids:
        n = len(ik[j + "|frames"])
        assert ik[j + "|q"].shape == (n, 14)
        assert ik[j + "|base_traj"].shape == (n, 4)
        assert ik[j + "|head"].shape == (n, 2)
        assert hd[j + "|left__fingers"].shape == (n, 20) and hd[j + "|right__fingers"].shape == (n, 20)
        assert ob[j + "|obj_T"].shape == (n, 4, 4)
        assert np.all(np.diff(ik[j + "|tmap"]) >= 0)        # the human clock pauses while the robot moves from/to home
        for s in ("left", "right"):
            assert ik[j + "|" + s + "__win"].shape == (4,) and ik[j + "|" + s + "__w"].shape == (n,)
        assert set(np.unique(ob[j + "|obj_carrier"])) <= {-1, 0, 1}
        for a in (ik[j + "|q"], hd[j + "|left__fingers"], ob[j + "|obj_T"]):
            assert np.all(np.isfinite(a))


def test_joint_limits_respected():
    from arcade_retarget.paths import DEFAULT_URDF
    pin = pytest.importorskip("pinocchio")
    if not os.path.exists(DEFAULT_URDF):
        pytest.skip("robot description not fetched (retarget/robotis_ffw_sh5/fetch_robot.sh)")
    m = pin.buildModelFromUrdf(DEFAULT_URDF)
    ik = np.load(RT + "_ik.npz")
    for j in sorted(k.split("|")[0] for k in ik.files if k.endswith("|frames")):
        for c, name in enumerate(ik[j + "|joint_names"]):
            iq = m.joints[m.getJointId(str(name))].idx_q
            q = ik[j + "|q"][:, c]
            assert q.min() >= m.lowerPositionLimit[iq] - 1e-4 and q.max() <= m.upperPositionLimit[iq] + 1e-4, (j, name)


def test_lerobot_v21_layout():
    pq = pytest.importorskip("pyarrow.parquet")
    info = json.load(open(os.path.join(LR21, "meta", "info.json")))
    assert info["codebase_version"] == "v2.1" and info["fps"] == 20 and info["robot_type"] == "ffw_sh5_rev1"
    eps = [json.loads(l) for l in open(os.path.join(LR21, "meta", "episodes.jsonl"))]
    assert info["total_episodes"] == len(eps)
    total = 0
    for e in eps:
        t = pq.read_table(os.path.join(LR21, info["data_path"].format(episode_chunk=0, episode_index=e["episode_index"])))
        assert t.num_rows == e["length"]
        s = np.array(t.column("observation.state").to_pylist(), np.float32)
        a = np.array(t.column("action").to_pylist(), np.float32)
        assert s.shape[1] == info["features"]["observation.state"]["shape"][0] == len(info["features"]["observation.state"]["names"])
        assert np.allclose(a[:-1], s[1:]) and np.allclose(a[-1], s[-1])
        ts = np.array(t.column("timestamp").to_pylist())
        assert np.allclose(np.diff(ts), 1.0 / info["fps"], atol=1e-5)
        assert np.all(np.diff(np.array(t.column("source_frame").to_pylist())) >= 0)
        total += t.num_rows
    assert total == info["total_frames"]


def test_lerobot_v30_matches_v21():
    pq = pytest.importorskip("pyarrow.parquet")
    info = json.load(open(os.path.join(LR30, "meta", "info.json")))
    assert info["codebase_version"] == "v3.0" and info["fps"] == 20
    t30 = pq.read_table(os.path.join(LR30, "data", "chunk-000", "file-000.parquet"))
    s30 = np.array(t30.column("observation.state").to_pylist(), np.float32)
    s21 = np.concatenate([np.array(pq.read_table(os.path.join(LR21, "data", "chunk-000", f"episode_{i:06d}.parquet"))
                                   .column("observation.state").to_pylist(), np.float32) for i in range(2)])
    assert np.array_equal(s30, s21)


def test_tasks_follow_the_events():
    from arcade_retarget.export_lerobot import task_of
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    assert task_of(obm["J03826_left"]) == ("Pick up the bottle from the checkout counter with the left hand, "
                                          "pass it to the right hand, and put it down.")
    assert task_of(obm["J02562_right"]) == "Pick up the box from the checkout counter with the right hand and put it down."
    tasks = [json.loads(l)["task"] for l in open(os.path.join(LR21, "meta", "tasks.jsonl"))]
    assert sorted(tasks) == sorted(task_of(obm[j]) for j in obm)


def test_solver_reproduces_sample(tmp_path):
    """Re-run the solver on the sample's hand-over episode and compare with the released trajectory.

    Needs the solver extra, the robot description (retarget/robotis_ffw_sh5/fetch_robot.sh) and the
    ARCADE-Checkout-Human sample next to this repository (or ARCADE_HUMAN_RELEASE=/path).
    """
    import subprocess
    import sys
    from arcade_retarget.paths import DEFAULT_URDF
    pytest.importorskip("pinocchio")
    import scipy
    if tuple(int(x) for x in scipy.__version__.split(".")[:2]) < (1, 16):
        pytest.skip("the solver needs SciPy >= 1.16")
    rel = os.environ.get("ARCADE_HUMAN_RELEASE", HUMAN_SAMPLE)
    if not os.path.exists(os.path.join(rel, "meta", "info.json")) or not os.path.exists(DEFAULT_URDF):
        pytest.skip("needs the ARCADE-Checkout-Human sample (or ARCADE_HUMAN_RELEASE) and the fetched robot description")
    out = str(tmp_path / "ffw")
    subprocess.run([sys.executable, "-m", "arcade_retarget.ffw_sh5", "--release", rel, "--out", out,
                    "--episodes", "J03826_left", "--workers", "1"], check=True)
    a, b = np.load(RT + "_ik.npz"), np.load(out + "_ik.npz")
    j = "J03826_left"
    assert a[j + "|q"].shape == b[j + "|q"].shape
    assert np.abs(a[j + "|q"] - b[j + "|q"]).max() < 0.05          # rad (measured 0.0004)
    ea, eb = a[j + "|right__err"][:, 0], b[j + "|right__err"][:, 0]
    assert abs(np.median(ea) - np.median(eb)) < 1.0                  # mm


def test_export_without_release_warns_and_puts_all_in_train(tmp_path):
    pytest.importorskip("pyarrow")
    from arcade_retarget.export_lerobot import export
    out = str(tmp_path / "lr")
    with pytest.warns(UserWarning, match="train"):
        info = export(RT, out)
    assert info["splits"] == {"train": f"0:{info['total_episodes']}"}
    assert not os.path.exists(os.path.join(out, "meta", "splits.json"))
