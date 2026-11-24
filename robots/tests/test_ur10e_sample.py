"""Checks on the UR10e + Robotiq 2F-140 sample: raw outputs, LeRobot exports, tasks and the robot description."""
import json
import os

import numpy as np
import pytest

from arcade_retarget import ur10e_2f140 as ur

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..", "samples")
RT = os.path.join(ROOT, "ur10e_2f140_sample", "ur10e_2f140")
LR21 = os.path.join(ROOT, "lerobot_ur10e_2f140_v2.1")
LR30 = os.path.join(ROOT, "lerobot_ur10e_2f140_v3.0")
HUMAN_SAMPLE = os.path.join(HERE, "..", "..", "human", "samples", "arcade_human_sample")
EPS = ["J01160_right", "J05489_left"]


def _jids(ik):
    return sorted(k.split("|")[0] for k in ik.files if k.endswith("|frames"))


def test_raw_outputs_consistent():
    ik, ob = np.load(RT + "_ik.npz"), np.load(RT + "_obj.npz")
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    upper = ur.config()["gripper"]["upper_limit"]
    assert _jids(ik) == EPS
    for j in EPS:
        n = len(ik[j + "|frames"])
        assert list(ik[j + "|joint_names"]) == ur.JOINT_NAMES and list(ik[j + "|gripper_names"]) == ur.GRIPPER_NAMES
        assert ik[j + "|q"].shape == (n, 12) and ik[j + "|gripper"].shape == (n, 2) and ik[j + "|phase"].shape == (n, 2)
        for s in ur.SIDES:
            assert ik[f"{j}|{s}__gripper_T"].shape == (n, 4, 4)
        tm = ik[j + "|tmap"]
        assert np.all(np.diff(tm) >= 0) and tm.min() >= 0          # the source clock never runs backwards
        g = ik[j + "|gripper"]
        assert g.min() >= 0 and g.max() <= upper
        assert set(np.unique(ik[j + "|phase"])) <= {-1, 0, 1, 2}
        assert ob[j + "|obj_T"].shape == (n, 4, 4) and np.all(np.isfinite(ob[j + "|obj_T"]))
        assert np.array_equal(ob[j + "|obj_holding"], ik[j + "|phase"] == 1)
        assert obm[j]["holding"] == ur.holding_runs(ob[j + "|obj_holding"])
        for a in (ik[j + "|q"], g):
            assert np.all(np.isfinite(a))


def test_tasks_follow_the_robot_grasps():
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    assert ur.task_sentence(obm["J05489_left"]["dims"]["shape"], obm["J05489_left"]["holding"]) == (
        "Pick up the box from the checkout counter with the left arm, pass it to the right arm, and put it down.")
    assert ur.task_sentence(obm["J01160_right"]["dims"]["shape"], obm["J01160_right"]["holding"]) == (
        "Pick up the bottle from the checkout counter with the right arm and put it down.")
    assert [obm[j]["task_kind"] for j in EPS] == ["one_arm", "pass"]


def test_lerobot_v21_matches_raw():
    pq = pytest.importorskip("pyarrow.parquet")
    info = json.load(open(os.path.join(LR21, "meta", "info.json")))
    assert info["codebase_version"] == "v2.1" and info["fps"] == 20 and info["robot_type"] == ur.ROBOT_TYPE
    assert info["features"]["observation.state"]["names"] == ur.STATE_NAMES
    ik, ob = np.load(RT + "_ik.npz"), np.load(RT + "_obj.npz")
    h = json.load(open(RT + "_ik.json"))["counter_h"]
    eps = [json.loads(line) for line in open(os.path.join(LR21, "meta", "episodes.jsonl"))]
    assert [e["source_episode_id"] for e in eps] == EPS
    for e in eps:
        j = e["source_episode_id"]
        t = pq.read_table(os.path.join(LR21, info["data_path"].format(episode_chunk=0, episode_index=e["episode_index"])))
        s = np.array(t.column("observation.state").to_pylist(), np.float32)
        a = np.array(t.column("action").to_pylist(), np.float32)
        env = np.array(t.column("observation.environment_state").to_pylist(), np.float32)
        assert s.shape == (e["length"], 14)
        assert np.array_equal(s, np.concatenate([ik[j + "|q"], ik[j + "|gripper"]], 1))
        assert np.allclose(a[:-1], s[1:]) and np.allclose(a[-1], s[-1])
        assert np.allclose(env[:, :3], ob[j + "|obj_T"][:, :3, 3] + [0, 0, h], atol=1e-5)
        assert np.array_equal(env[:, 7:9] > 0.5, ob[j + "|obj_holding"])
        assert np.allclose(np.array(t.column("source_frame").to_pylist()), ik[j + "|tmap"])
    mod = json.load(open(os.path.join(LR21, "meta", "modality.json")))
    assert [mod["state"][k]["end"] - mod["state"][k]["start"] for k in ("left_arm", "right_arm", "left_gripper", "right_gripper")] == [6, 6, 1, 1]


def test_lerobot_v30_matches_v21():
    pq = pytest.importorskip("pyarrow.parquet")
    info = json.load(open(os.path.join(LR30, "meta", "info.json")))
    assert info["codebase_version"] == "v3.0" and info["robot_type"] == ur.ROBOT_TYPE
    t30 = pq.read_table(os.path.join(LR30, "data", "chunk-000", "file-000.parquet"))
    s30 = np.array(t30.column("observation.state").to_pylist(), np.float32)
    s21 = np.concatenate([np.array(pq.read_table(os.path.join(LR21, "data", "chunk-000", f"episode_{i:06d}.parquet"))
                                   .column("observation.state").to_pylist(), np.float32) for i in range(2)])
    assert np.array_equal(s30, s21)


def test_export_warns_when_the_release_has_none_of_the_episodes(tmp_path):
    pytest.importorskip("pyarrow")
    if not os.path.exists(os.path.join(HUMAN_SAMPLE, "meta", "info.json")):
        pytest.skip("needs the ARCADE-Checkout-Human sample next to this directory")
    from arcade_retarget.export_lerobot import export
    with pytest.warns(UserWarning, match="none of the exported episodes"):
        info = export(RT, str(tmp_path / "lr"), release=HUMAN_SAMPLE)
    assert info["splits"] == {"train": "0:2"} and info["robot_type"] == ur.ROBOT_TYPE


def test_gripper_table():
    g = ur.config()["gripper"]
    assert np.all(np.diff(g["pad_gap_m"]) < 0)                              # closing narrows the gap
    assert abs(float(ur.gripper_gap(0.0)) - g["pad_gap_m"][0]) < 1e-9


def test_urdf_fk_reproduces_the_gripper_poses():
    """The joint positions on the fetched URDF put both grippers where the raw outputs say."""
    pin = pytest.importorskip("pinocchio")
    if not os.path.exists(ur.DEFAULT_URDF):
        pytest.skip("robot description not built (retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh)")
    m = pin.buildModelFromUrdf(ur.DEFAULT_URDF)
    d = m.createData()
    idx = [m.joints[m.getJointId(n)].idx_q for n in ur.STATE_NAMES]
    lo, hi = m.lowerPositionLimit[idx], m.upperPositionLimit[idx]
    ik = np.load(RT + "_ik.npz")
    h = json.load(open(RT + "_ik.json"))["counter_h"]
    worst = 0.0
    for j in EPS:
        x = np.concatenate([ik[j + "|q"], ik[j + "|gripper"]], 1)
        assert np.all(x >= lo - 1e-6) and np.all(x <= hi + 1e-6), j                      # within the URDF limits
        for t in range(0, len(x), 25):
            q = pin.neutral(m)
            q[idx] = x[t]
            pin.framesForwardKinematics(m, d, q)
            for s in ur.SIDES:
                M = d.oMf[m.getFrameId(f"{s}_robotiq_arg2f_base_link")].homogeneous
                T = ik[f"{j}|{s}__gripper_T"][t].astype(np.float64)
                T[2, 3] += h
                worst = max(worst, float(np.abs(M - T).max()))
    assert worst < 1e-5, worst                                                           # measured 2e-7


def test_mujoco_replay_matches_the_gripper_poses():
    """The preview renderer's MuJoCo model (from the same URDF) puts the grippers where the raw outputs say."""
    pytest.importorskip("mujoco")
    if not os.path.exists(ur.DEFAULT_URDF):
        pytest.skip("robot description not built (retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh)")
    from arcade_retarget.render import UR10eScene
    ik = np.load(RT + "_ik.npz")
    meta = json.load(open(RT + "_ik.json"))
    sc = UR10eScene(meta["counter"], meta["counter_h"], {})
    worst = 0.0
    for j in EPS:
        x = np.concatenate([ik[j + "|q"], ik[j + "|gripper"]], 1)
        for t in range(0, len(x), 25):
            sc.set_robot(x[t])
            sc.forward()
            for s in ur.SIDES:
                b = sc.model.body(f"{s}_robotiq_arg2f_base_link").id
                T = ik[f"{j}|{s}__gripper_T"][t].astype(np.float64)
                worst = max(worst, float(np.abs(sc.data.xpos[b] - T[:3, 3] - [0, 0, meta["counter_h"]]).max()),
                            float(np.abs(sc.data.xmat[b].reshape(3, 3) - T[:3, :3]).max()))
    assert worst < 1e-5, worst                                                           # measured 4e-7
