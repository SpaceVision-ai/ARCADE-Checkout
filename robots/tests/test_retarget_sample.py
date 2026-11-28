"""Checks on the shipped samples: raw retargeting outputs and the LeRobot exports (3 episodes)."""
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
    assert jids == ["J00601_right", "J02562_right", "J03826_left"]
    assert ob["J03826_left|obj_holding"].all(1).any()                # during the hand-over both hands hold
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
    from arcade_retarget.urdf_fk import Chain
    if not os.path.exists(DEFAULT_URDF):
        pytest.skip("robot description not fetched (retarget/robotis_ffw_sh5/fetch_robot.sh)")
    limits = Chain(DEFAULT_URDF).limits
    ik = np.load(RT + "_ik.npz")
    for j in sorted(k.split("|")[0] for k in ik.files if k.endswith("|frames")):
        for c, name in enumerate(ik[j + "|joint_names"]):
            lo, hi = limits[str(name)]
            q = ik[j + "|q"][:, c]
            assert q.min() >= lo - 1e-4 and q.max() <= hi + 1e-4, (j, name)


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
                                   .column("observation.state").to_pylist(), np.float32) for i in range(3)])
    assert np.array_equal(s30, s21)


def test_tasks_follow_the_events():
    from arcade_retarget.export_lerobot import task_of
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    assert task_of(obm["J03826_left"]) == ("Pick up the bottle from the checkout counter with the left hand, "
                                          "pass it to the right hand, and put it down.")
    assert task_of(obm["J02562_right"]) == "Pick up the box from the checkout counter with the right hand and put it down."
    tasks = [json.loads(l)["task"] for l in open(os.path.join(LR21, "meta", "tasks.jsonl"))]
    assert sorted(tasks) == sorted({task_of(obm[j]) for j in obm})


def test_every_episode_is_released_with_its_check():
    """The sample holds two episodes that pass the robot-side check and rejected ones, labelled with the rules they fail."""
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    eps = [json.loads(line) for line in open(os.path.join(LR21, "meta", "episodes.jsonl"))]
    assert [e["source_episode_id"] for e in eps] == ["J02562_right", "J03826_left", "J00601_right"]
    for e in eps:
        c = obm[e["source_episode_id"]]["check"]
        assert e["check_passed"] == c["passed"] == (not c["failed"]) and e["check_failed"] == c["failed"]
    info = json.load(open(os.path.join(LR21, "meta", "info.json")))
    n_ok = sum(e["check_passed"] for e in eps)
    assert [e["check_passed"] for e in eps] == [True] * n_ok + [False] * (len(eps) - n_ok)      # checked episodes first
    assert info["splits"]["rejected"] == f"{n_ok}:{len(eps)}"
    assert info["features"]["observation.environment_state"]["names"][7:] == ["left_holding", "right_holding"]


def test_export_without_release_warns_and_puts_all_in_train(tmp_path):
    pytest.importorskip("pyarrow")
    from arcade_retarget.export_lerobot import export
    out = str(tmp_path / "lr")
    with pytest.warns(UserWarning, match="train"):
        info = export(RT, out)
    assert info["splits"] == {"train": f"0:{info['total_episodes']}"}
    assert not os.path.exists(os.path.join(out, "meta", "splits.json"))
