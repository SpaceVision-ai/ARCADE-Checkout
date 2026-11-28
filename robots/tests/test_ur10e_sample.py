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
EPS = ["J00601_right", "J02562_right", "J03826_left"]
ORDER = ["J02562_right", "J00601_right", "J03826_left"]   # LeRobot order: checked episodes first, then the rejected ones


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
    assert ur.task_sentence(obm["J03826_left"]["dims"]["shape"], obm["J03826_left"]["holding"]) == (
        "Pick up the bottle from the checkout counter with the left arm, pass it to the right arm, and put it down.")
    assert ur.task_sentence(obm["J02562_right"]["dims"]["shape"], obm["J02562_right"]["holding"]) == (
        "Pick up the box from the checkout counter with the right arm, pass it to the left arm, and put it down.")
    assert [obm[j]["task_kind"] for j in EPS] == ["pass", "pass", "pass"]

def test_every_episode_is_released_with_its_check():
    """The sample holds two episodes that pass the robot-side check and rejected ones, labelled with the rules they fail."""
    obm = json.load(open(RT + "_obj.json"))["episodes"]
    eps = [json.loads(line) for line in open(os.path.join(LR21, "meta", "episodes.jsonl"))]
    assert [e["source_episode_id"] for e in eps] == ORDER
    for e in eps:
        c = obm[e["source_episode_id"]]["check"]
        assert e["check_passed"] == c["passed"] == (not c["failed"]) and e["check_failed"] == c["failed"]
    info = json.load(open(os.path.join(LR21, "meta", "info.json")))
    n_ok = sum(e["check_passed"] for e in eps)
    assert [e["check_passed"] for e in eps] == [True] * n_ok + [False] * (len(eps) - n_ok)      # checked episodes first
    assert info["splits"]["rejected"] == f"{n_ok}:{len(eps)}"
    assert info["features"]["observation.environment_state"]["names"][7:] == ["left_holding", "right_holding"]


def test_lerobot_v21_matches_raw():
    pq = pytest.importorskip("pyarrow.parquet")
    info = json.load(open(os.path.join(LR21, "meta", "info.json")))
    assert info["codebase_version"] == "v2.1" and info["fps"] == 20 and info["robot_type"] == ur.ROBOT_TYPE
    assert info["features"]["observation.state"]["names"] == ur.STATE_NAMES
    ik, ob = np.load(RT + "_ik.npz"), np.load(RT + "_obj.npz")
    h = json.load(open(RT + "_ik.json"))["counter_h"]
    eps = [json.loads(line) for line in open(os.path.join(LR21, "meta", "episodes.jsonl"))]
    assert [e["source_episode_id"] for e in eps] == ORDER
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
                                   .column("observation.state").to_pylist(), np.float32) for i in range(len(EPS))])
    assert np.array_equal(s30, s21)


def test_export_with_the_release_gives_time_splits_and_the_rejected_split(tmp_path):
    pytest.importorskip("pyarrow")
    if not os.path.exists(os.path.join(HUMAN_SAMPLE, "meta", "info.json")):
        pytest.skip("needs the ARCADE-Checkout-Human sample next to this directory")
    from arcade_retarget.export_lerobot import export
    info = export(RT, str(tmp_path / "lr"), release=HUMAN_SAMPLE)
    assert info["splits"] == {"train": "0:1", "rejected": "1:3"} and info["robot_type"] == ur.ROBOT_TYPE


def test_gripper_table():
    g = ur.config()["gripper"]
    assert np.all(np.diff(g["pad_gap_m"]) < 0)                              # closing narrows the gap
    assert abs(float(ur.gripper_gap(0.0)) - g["pad_gap_m"][0]) < 1e-9
    assert np.all(np.diff(g["urdf_pad_gap_m"]) < 0) and len(g["urdf_pad_gap_m"]) == len(g["urdf_finger_joint"])
    q = np.array([0.294, 0.373, 0.648])                                     # the holds of the sample episodes
    u = ur.urdf_finger_joint(q)
    assert np.all(u < q) and np.all(u >= 0)                                 # the fetched URDF closes further per radian
    assert np.allclose(np.interp(u, g["urdf_finger_joint"], g["urdf_pad_gap_m"]), ur.gripper_gap(q), atol=2e-4)


def test_urdf_pads_open_as_the_table_says():
    """On the fetched URDF, the gap between the inner-finger pads matches ``urdf_pad_gap_m``."""
    from arcade_retarget.urdf_fk import Chain
    if not os.path.exists(ur.DEFAULT_URDF):
        pytest.skip("robot description not built (retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh)")
    c = Chain(ur.DEFAULT_URDF)
    g = ur.config()["gripper"]
    assert c.mimic == ur.mimic_joints()
    for qf, gap in list(zip(g["urdf_finger_joint"], g["urdf_pad_gap_m"]))[::4]:
        T = c.link_poses({"left_finger_joint": qf})                          # the other finger joints follow by <mimic>
        A, B = (T[f"left_{s}_inner_finger_pad"] for s in ("left", "right"))
        assert abs(abs((B[:3, 3] - A[:3, 3]) @ A[:3, 2]) - 0.0075 - gap) < 2e-4   # pad box: 7.5 mm thick along its z


def test_urdf_fk_reproduces_the_gripper_poses():
    """The joint positions on the fetched URDF put both grippers where the raw outputs say."""
    from arcade_retarget.urdf_fk import Chain
    if not os.path.exists(ur.DEFAULT_URDF):
        pytest.skip("robot description not built (retarget/universal_robots_ur10e_robotiq_2f140/fetch_robot.sh)")
    c = Chain(ur.DEFAULT_URDF)
    lo, hi = (np.array([c.limits[n][k] for n in ur.STATE_NAMES]) for k in (0, 1))
    ik = np.load(RT + "_ik.npz")
    h = json.load(open(RT + "_ik.json"))["counter_h"]
    worst = 0.0
    for j in EPS:
        x = np.concatenate([ik[j + "|q"], ik[j + "|gripper"]], 1).astype(np.float64)
        assert np.all(x >= lo - 1e-6) and np.all(x <= hi + 1e-6), j                      # within the URDF limits
        for t in range(0, len(x), 25):
            poses = c.link_poses(dict(zip(ur.STATE_NAMES, x[t])))
            for s in ur.SIDES:
                T = ik[f"{j}|{s}__gripper_T"][t].astype(np.float64)
                T[2, 3] += h
                worst = max(worst, float(np.abs(poses[f"{s}_robotiq_arg2f_base_link"] - T).max()))
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
