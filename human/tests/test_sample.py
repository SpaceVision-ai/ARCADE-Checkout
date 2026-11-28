import os

import numpy as np
import pytest

from arcade_human import ArcadeHuman
from arcade_human import schema as S
from arcade_human.geometry import matrix_to_quat_xyzw, quat_xyzw_to_matrix
from arcade_human.validate import validate

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "arcade_human_sample")


@pytest.fixture(scope="module")
def ds():
    return ArcadeHuman(SAMPLE)


def test_sample_validates():
    errors, warns = validate(SAMPLE)
    assert errors == []
    assert warns == []


def test_check_labels(ds):
    """Every episode is released; the quality check labels the ones that fail and why."""
    assert ds.passed_ids == ["J00601_right", "J02562_right", "J03826_left"] and ds.info["n_episodes_passed"] == 3
    bad = ds.load("J06564_right")
    assert not bad.check_passed and bad.check_failed == ["held_product_vs_masks", "product_vs_masks"]
    assert set(bad.check_failed) <= set(S.CHECK_RULES) and set(ds.info["check_rules"]) == set(S.CHECK_RULES)
    for eid in ds.passed_ids:
        assert ds.load(eid).check_passed and ds.load(eid).check_failed == []
    from arcade_human.splits import time_split
    assert time_split(ds)["rejected"] == ["J06564_right"]


def test_index_matches_hdf5(ds):
    assert len(ds) == ds.info["n_episodes"] == 4
    for ep in ds:
        assert len(ep) == ds.row(ep.episode_id)["n_frames"]
        for path, (spec, _) in S.EPISODE_LAYOUT.items():
            assert path in ep.data


def test_wrist_frames_are_rotations(ds):
    for ep in ds:
        for side in S.SIDES:
            v = ep[f"wrist/{side}/valid"]
            R = ep.wrist_matrix(side)[v][:, :3, :3]
            assert np.allclose(np.einsum("nij,nkj->nik", R, R), np.eye(3), atol=1e-4)
            assert np.allclose(np.linalg.det(R), 1.0, atol=1e-4)


def test_resting_product_on_counter(ds):
    for ep in ds:
        st = ep["object/state"]
        rest = ep["object/valid"] & ((st == 0) | (st == 3))
        for t in np.nonzero(rest)[0][:5]:
            V = ep.object_vertices_world(int(t))
            assert abs(V[:, 2].min()) < 0.03, (ep.episode_id, t, V[:, 2].min())


def test_events_and_holding(ds):
    for ep in ds:
        for e in ep.events:
            hold = ep[f"interaction/{e['hand']}/holding"]
            if e["kind"] == "grasp":
                assert hold[e["frame"]]
            else:
                assert hold[max(e["frame"] - 1, 0)]


def test_masks(ds):
    ep_id = "J03826_left"
    meta = ds.segmentation_meta(ep_id)
    assert meta["hero_instance"]
    m = ds.product_mask(ep_id, "top", 80)
    assert m is not None and m.dtype == bool and m.any()


def test_release_without_masks_validates(tmp_path):
    """The masks are an optional download: without segmentation/ the release still validates."""
    import shutil
    root = tmp_path / "core"
    shutil.copytree(SAMPLE, root, ignore=shutil.ignore_patterns("segmentation"))
    errors, warns = validate(str(root))
    assert errors == [] and any("masks were not downloaded" in w for w in warns)


def test_unpacked_masks_read_the_same(ds, tmp_path):
    """masks.zip and the folder it unpacks to give the same masks."""
    import shutil
    import zipfile
    ep_id = "J03826_left"
    root = tmp_path / "release"
    shutil.copytree(SAMPLE, root)
    seg = root / "segmentation" / ep_id
    with zipfile.ZipFile(seg / S.MASKS_ZIP) as z:
        z.extractall(seg / "masks")
    (seg / S.MASKS_ZIP).unlink()
    unpacked = ArcadeHuman(str(root))
    assert unpacked.mask_files(ep_id) == ds.mask_files(ep_id)
    for view in ("left", "right", "top"):
        a, b = ds.masks(ep_id, view, 80), unpacked.masks(ep_id, view, 80)
        assert a.keys() == b.keys() and all(np.array_equal(a[t], b[t]) for t in a)


def test_task_kind_and_sentence(ds):
    ep = ds.load("J03826_left")
    assert ep.task_kind == ep.attrs["task_kind"] == "pass"
    assert ep.attrs["first_grasp_hand"] == "left" and ep.attrs["last_release_hand"] == "right"
    assert ep.task == ("Pick up the bottle from the checkout counter with the left hand, pass it to the right hand, "
                       "and put it down.")
    ep = ds.load("J02562_right")
    assert ep.task_kind == "one_hand"
    assert ep.task == "Pick up the box from the checkout counter with the right hand and put it down."


def test_task_kinds():
    from arcade_human.tasks import hands_order, kind_of
    ev = lambda *xs: [dict(frame=f, hand=h, kind=k) for f, h, k in xs]
    assert kind_of(*hands_order(ev((1, "right", "grasp"), (9, "right", "release")))) == "one_hand"
    assert kind_of(*hands_order(ev((1, "left", "grasp"), (4, "right", "grasp"), (6, "left", "release"),
                                    (9, "right", "release")))) == "pass"
    assert kind_of(*hands_order(ev((1, "right", "grasp"), (4, "left", "grasp"), (6, "left", "release"),
                                    (9, "right", "release")))) == "both_hands"


def test_quaternion_roundtrip():
    rng = np.random.default_rng(0)
    q = rng.normal(size=(50, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    q[q[:, 3] < 0] *= -1
    assert np.allclose(matrix_to_quat_xyzw(quat_xyzw_to_matrix(q)), q, atol=1e-8)


def _signed_volume(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0)


@pytest.mark.parametrize("perm", [(0, 1, 2), (1, 2, 0), (2, 0, 1), (1, 0, 2), (0, 2, 1), (2, 1, 0)])
def test_product_axes_and_bake_are_proper(tmp_path, perm):
    from arcade_human.geometry import bake_obj, product_axes
    A = product_axes(perm)
    assert np.allclose(A @ A.T, np.eye(3)) and np.isclose(np.linalg.det(A), 1.0)
    # an asymmetric, closed tetrahedron with outward faces
    V = np.array([[0.0, 0, 0], [0.3, 0, 0], [0, 0.2, 0], [0, 0, 0.1]]) + [1.0, 2.0, 3.0]
    F = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    src, dst = tmp_path / "src.obj", tmp_path / "dst.obj"
    src.write_text("".join("v %f %f %f\n" % tuple(v) for v in V) + "".join("f %d %d %d\n" % tuple(f + 1) for f in F))
    bake_obj(str(src), str(dst), perm)
    lines = dst.read_text().splitlines()
    Vb = np.array([[float(x) for x in l.split()[1:4]] for l in lines if l.startswith("v ")])
    Fb = np.array([[int(x) - 1 for x in l.split()[1:4]] for l in lines if l.startswith("f ")])
    c = (V.max(0) + V.min(0)) / 2
    assert np.allclose(Vb, (V - c) @ A.T, atol=1e-6)
    assert (Fb == F).all()                                   # winding untouched
    assert _signed_volume(Vb, Fb) == pytest.approx(_signed_volume(V, F), rel=1e-4)   # not mirrored


def test_time_split_has_no_frame_leakage(ds):
    from arcade_human.splits import time_split
    s = time_split(ds, fractions=(0.5, 0.5), names=("train", "test"))
    rng = {r["episode_id"]: r["source_frame_range"] for r in ds.index}
    frames = {k: {f for e in v for f in range(rng[e][0], rng[e][1] + 1)} for k, v in s.items() if k != "boundary"}
    assert not (frames["train"] & frames["test"])
    assert sorted(sum(s.values(), [])) == sorted(ds.episode_ids)


def test_product_split_drops_overlapping_episodes(ds):
    from arcade_human.splits import product_split
    rng = {r["episode_id"]: r["source_frame_range"] for r in ds.index}
    s = product_split(ds, "bottle_c")
    frames = {k: {f for e in s[k] for f in range(rng[e][0], rng[e][1] + 1)} for k in ("train", "test")}
    assert s["test"] == ["J03826_left"] and not (frames["train"] & frames["test"])
    assert sorted(s["train"] + s["test"] + s["dropped"]) == sorted(ds.passed_ids) and s["rejected"] == ["J06564_right"]


def test_baked_mesh_is_named(ds):
    head = open(os.path.join(SAMPLE, ds.load("J03826_left").attrs["product_mesh"])).read(400)
    assert "o bottle_c" in head and "tmp" not in head


def test_core_handling_ignores_context_and_flags_repeats():
    from arcade_human.tasks import core_handling
    n = 100
    L, R = np.zeros(n, bool), np.zeros(n, bool)
    L[2:12] = True                       # the end of a neighbouring handling, in the lead-in
    R[40:60] = True                      # the episode's own handling: right hand only
    assert core_handling({"left": L, "right": R}, (30, 80)) == ("one_hand", "right", "right")
    L2 = np.zeros(n, bool)
    L2[50:70] = True                     # left joins and puts it down: a pass
    assert core_handling({"left": L2, "right": R}, (30, 80)) == ("pass", "right", "left")
    R2 = R.copy()
    R2[70:78] = True                     # put down at 60, picked up again at 70: repeated
    assert core_handling({"left": np.zeros(n, bool), "right": R2}, (30, 80))[0] == "repeated"


def test_body_filled_flags(ds):
    for ep in ds:
        f, v = ep["body/filled"], ep["body/valid"]
        assert f.shape == v.shape and not (f & ~v).any()     # filled joints are a subset of valid ones


def test_carrying_is_one_hand_mostly_within_holding(ds):
    ep = ds.load("J03826_left")
    L, R = ep["interaction/left/carrying"], ep["interaction/right/carrying"]
    assert L.any() and R.any() and not (L & R).any()                       # a hand-over switches the carrier
    for s in ("left", "right"):
        c, h = ep[f"interaction/{s}/carrying"], ep[f"interaction/{s}/holding"]
        assert (c & ~h).sum() <= 3
