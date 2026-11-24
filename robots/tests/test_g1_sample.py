"""Checks on the Unitree G1 + Dex3-1 sample: raw outputs, LeRobot exports, tasks, physics flags and the robot description."""
import json
import os

import numpy as np
import pytest

from arcade_retarget import g1_dex3 as g1

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..", "samples")
RT = os.path.join(ROOT, "g1_dex3_sample", "g1_dex3")
LR21 = os.path.join(ROOT, "lerobot_g1_dex3_v2.1")
LR30 = os.path.join(ROOT, "lerobot_g1_dex3_v3.0")
EPS = ["J02771_right", "J08320_left"]


def _jids(ik):
    return sorted(k.split("|")[0] for k in ik.files if k.endswith("|frames"))


def test_names():
    assert len(g1.JOINT_NAMES) == 43 and len(set(g1.JOINT_NAMES)) == 43
    assert len(g1.STATE_NAMES) == 50 and sum(k for _, k in g1.GROUPS) == 50


def test_raw_outputs_consistent():
    ik, ob = np.load(RT + "_ik.npz"), np.load(RT + "_obj.npz")
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    assert _jids(ik) == EPS
    for j in EPS:
        n = len(ik[j + "|frames"])
        assert list(ik[j + "|joint_names"]) == g1.JOINT_NAMES
        assert ik[j + "|q"].shape == (n, 43) and ik[j + "|pelvis"].shape == (n, 7) and ik[j + "|phase"].shape == (n, 2)
        assert ik[j + "|com"].shape == (n, 3)
        for s in g1.SIDES:
            assert ik[f"{j}|{s}__tips"].shape == (n, 3, 3)
        tm = ik[j + "|tmap"]
        assert np.all(np.diff(tm) >= 0) and tm.min() >= 0                  # the source clock never runs backwards
        assert np.allclose(np.linalg.norm(ik[j + "|pelvis"][:, 3:], axis=1), 1, atol=1e-5)
        assert set(np.unique(ik[j + "|phase"])) <= {0, 1, 2, 3}
        assert ob[j + "|obj_T"].shape == (n, 4, 4) and np.all(np.isfinite(ob[j + "|obj_T"]))
        assert np.array_equal(ob[j + "|obj_holding"], ik[j + "|phase"] == 2)
        assert obm[j]["holding"] == g1.holding_runs(ob[j + "|obj_holding"])
        holds = sorted((h["hand"], h["start"], h["end"]) for h in obm[j]["physics"]["holds"])
        assert holds == sorted((h["hand"], h["start"], h["end"]) for h in obm[j]["holding"])
        assert obm[j]["physics"]["all_held"] == all(h["verdict"] in ("held", "no_carry") for h in obm[j]["physics"]["holds"])
        for a in (ik[j + "|q"], ik[j + "|pelvis"]):
            assert np.all(np.isfinite(a))


def test_tasks_follow_the_robot_holds():
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    assert g1.task_sentence(obm["J08320_left"]["dims"]["shape"], obm["J08320_left"]["holding"]) == (
        "Pick up the box from the checkout counter with the left hand, pass it to the right hand, and put it down.")
    assert g1.task_sentence(obm["J02771_right"]["dims"]["shape"], obm["J02771_right"]["holding"]) == (
        "Pick up the box from the checkout counter with the right hand and put it down.")
    assert [obm[j]["task_kind"] for j in EPS] == ["one_hand", "pass"]


def test_lerobot_v21_matches_raw():
    pq = pytest.importorskip("pyarrow.parquet")
    info = json.load(open(os.path.join(LR21, "meta", "info.json")))
    assert info["codebase_version"] == "v2.1" and info["fps"] == 20 and info["robot_type"] == g1.ROBOT_TYPE
    assert info["features"]["observation.state"]["names"] == g1.STATE_NAMES
    ik, ob = np.load(RT + "_ik.npz"), np.load(RT + "_obj.npz")
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    h = json.load(open(RT + "_ik.json"))["counter_h"]
    eps = [json.loads(line) for line in open(os.path.join(LR21, "meta", "episodes.jsonl"))]
    assert [e["source_episode_id"] for e in eps] == EPS
    for e in eps:
        j = e["source_episode_id"]
        assert e["physics_all_held"] == obm[j]["physics"]["all_held"]
        t = pq.read_table(os.path.join(LR21, info["data_path"].format(episode_chunk=0, episode_index=e["episode_index"])))
        s = np.array(t.column("observation.state").to_pylist(), np.float32)
        a = np.array(t.column("action").to_pylist(), np.float32)
        env = np.array(t.column("observation.environment_state").to_pylist(), np.float32)
        assert s.shape == (e["length"], 50)
        assert np.array_equal(s[:, :43], ik[j + "|q"])
        assert np.allclose(s[:, 43:], ik[j + "|pelvis"] + np.array([0, 0, h, 0, 0, 0, 0], np.float32), atol=1e-6)
        assert np.allclose(a[:-1], s[1:]) and np.allclose(a[-1], s[-1])
        assert np.allclose(env[:, :3], ob[j + "|obj_T"][:, :3, 3] + [0, 0, h], atol=1e-5)
        assert np.array_equal(env[:, 7:9] > 0.5, ob[j + "|obj_holding"])
        assert np.allclose(np.array(t.column("source_frame").to_pylist()), ik[j + "|tmap"])
    mod = json.load(open(os.path.join(LR21, "meta", "modality.json")))
    assert [mod["state"][k]["end"] - mod["state"][k]["start"] for k, _ in g1.GROUPS] == [k for _, k in g1.GROUPS]


def test_lerobot_v30_matches_v21():
    pq = pytest.importorskip("pyarrow.parquet")
    info = json.load(open(os.path.join(LR30, "meta", "info.json")))
    assert info["codebase_version"] == "v3.0" and info["robot_type"] == g1.ROBOT_TYPE
    t30 = pq.read_table(os.path.join(LR30, "data", "chunk-000", "file-000.parquet"))
    s30 = np.array(t30.column("observation.state").to_pylist(), np.float32)
    s21 = np.concatenate([np.array(pq.read_table(os.path.join(LR21, "data", "chunk-000", f"episode_{i:06d}.parquet"))
                                   .column("observation.state").to_pylist(), np.float32) for i in range(2)])
    assert np.array_equal(s30, s21)
    ep = pq.read_table(os.path.join(LR30, "meta", "episodes", "chunk-000", "file-000.parquet"))
    assert ep.column("physics_all_held").to_pylist() == [True, True]


def test_urdf_fk_reproduces_the_fingertips():
    """The joints and pelvis pose on the fetched URDF put the fingertip points where the raw outputs say."""
    pin = pytest.importorskip("pinocchio")
    if not os.path.exists(g1.DEFAULT_URDF):
        pytest.skip("robot description not fetched (retarget/unitree_g1_dex3/fetch_robot.sh)")
    m = g1.pin_model()
    d = m.createData()
    lo, hi = m.lowerPositionLimit[7:], m.upperPositionLimit[7:]
    ik = np.load(RT + "_ik.npz")
    worst = 0.0
    for j in EPS:
        q, p = ik[j + "|q"].astype(np.float64), ik[j + "|pelvis"].astype(np.float64)
        assert np.all(q >= lo - 1e-6) and np.all(q <= hi + 1e-6), j                     # within the URDF limits
        for t in range(0, len(q), 10):
            pin.framesForwardKinematics(m, d, g1.pin_configuration(q[t], p[t]))
            for s in g1.SIDES:
                tips = ik[f"{j}|{s}__tips"][t]
                for k, f in enumerate(g1.FINGERS):
                    worst = max(worst, float(np.abs(d.oMf[m.getFrameId(f"{s}_{f}_tip")].translation - tips[k]).max()))
    assert worst < 1e-5, worst                                                           # float32 storage


def test_mujoco_replay_matches_the_urdf():
    """The preview renderer's MuJoCo model (Unitree's MJCF) has the URDF's kinematics."""
    pin = pytest.importorskip("pinocchio")
    pytest.importorskip("mujoco")
    if not os.path.exists(g1.DEFAULT_MJCF):
        pytest.skip("robot description not fetched (retarget/unitree_g1_dex3/fetch_robot.sh)")
    from arcade_retarget.render import G1Scene
    ik = np.load(RT + "_ik.npz")
    meta = json.load(open(RT + "_ik.json"))
    h = meta["counter_h"]
    sc = G1Scene(meta["counter"], h, {})
    m = g1.pin_model()
    d = m.createData()
    links = ["left_wrist_yaw_link", "right_wrist_yaw_link", "left_hand_thumb_2_link", "right_hand_index_1_link",
             "left_ankle_roll_link", "torso_link"]
    worst = 0.0
    for j in EPS:
        q, p = ik[j + "|q"].astype(np.float64), ik[j + "|pelvis"].astype(np.float64)
        for t in range(0, len(q), 20):
            state = np.concatenate([q[t], p[t]])
            state[45] += h
            sc.set_robot(state)
            sc.forward()
            pin.framesForwardKinematics(m, d, g1.pin_configuration(q[t], p[t]))
            for link in links:
                T = d.oMf[m.getFrameId(link)]
                b = sc.model.body(link).id
                worst = max(worst, float(np.abs(sc.data.xpos[b] - T.translation - [0, 0, h]).max()),
                            float(np.abs(sc.data.xmat[b].reshape(3, 3) - T.rotation).max()))
    assert worst < 1e-4, worst                                                           # measured 1.5e-6
