"""Quality summary of a release: the numbers quoted in the README, computed from the files.

    arcade-human quality RELEASE            # markdown table
    arcade-human quality RELEASE --json     # machine-readable

Per-episode fractions are summarised as the median episode (and the minimum, where useful).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Dict

import numpy as np

from .reader import ArcadeHuman
from .splits import overlap_report

ARM_JOINTS = {"shoulders": (5, 6), "elbows": (7, 8), "wrists": (9, 10)}


def _event_agrees(hold: np.ndarray, frame: int, kind: str) -> bool:
    """Same rule as the validator: a grasp at f means holding at f; a release at f means holding at f-1
    and not at f+1 (one frame of tolerance)."""
    T = len(hold)
    if kind == "grasp":
        return bool(hold[frame])
    return bool(hold[max(frame - 1, 0)] and (frame + 1 >= T or not hold[frame + 1]))


def _iou_summary(held, rest, cover):
    if not held and not rest:
        return None
    H = np.concatenate(held) if held else np.zeros(0)
    R = np.concatenate(rest) if rest else np.zeros(0)
    A = np.concatenate([H, R])
    A = A[np.isfinite(A)]
    return dict(held_median=round(float(np.nanmedian(H)), 2), rest_median=round(float(np.nanmedian(R)), 2),
                frames_iou_ge_0_5_pct=round(100 * float(np.mean(A >= 0.5)), 1),
                frames_with_masks_pct=round(100 * float(np.median(cover)), 1))


def summarize(root: str) -> Dict:
    ds = ArcadeHuman(root)
    kinds, hands_first = Counter(), Counter()
    observed, iou_held, iou_rest, cover = [], [], [], []
    joint_ok, arm_ok, n_frames = Counter(), 0, 0
    n_events = agree = 0
    durations = []
    for ep in ds:
        k, first, last = ep.handling()
        kinds[k] += 1
        if k == "one_hand":
            hands_first[first] += 1
        durations.append(len(ep) / float(ep.attrs.get("fps", 19.94)))
        for s in ("left", "right"):
            observed.append(1.0 - float(np.mean(ep[f"hand/{s}/gap_filled"])))
        bv = ep["body/valid"]
        if "body/filled" in ep.data:                    # count measured joints, not fitted ones
            bv = bv & ~ep["body/filled"]
        for name, idx in ARM_JOINTS.items():
            joint_ok[name] += int(bv[:, list(idx)].sum())
        arm_ok += int(bv[:, [5, 6, 7, 8, 9, 10]].all(axis=1).sum())
        n_frames += len(ep)
        st = ep["object/state"]
        held = np.isin(st, (1, 2))
        if "object/mask_iou" in ep.data:
            iou = ep["object/mask_iou"].astype(np.float64)
            iou_held.append(iou[held]); iou_rest.append(iou[~held]); cover.append(float(np.isfinite(iou).mean()))
        for e in ep.events:
            n_events += 1
            agree += _event_agrees(ep[f"interaction/{e['hand']}/holding"].astype(bool), e["frame"], e["kind"])

    def med(x):
        return round(100 * float(np.median(x)), 1)

    ov = overlap_report(ds)
    return {
        "episodes": len(ds),
        "task_kinds": dict(pass_=kinds["pass"], both_hands=kinds["both_hands"], one_hand=kinds["one_hand"],
                           repeated=kinds["repeated"], one_hand_by_hand=dict(hands_first)),
        "duration_s": [round(min(durations), 1), round(max(durations), 1)],
        "episode_frames": ov["episode_frames"], "unique_session_frames": ov["unique_session_frames"],
        "unique_minutes": ov["unique_minutes"],
        "hands_observed_pct": dict(median_episode_hand=med(observed), min=round(100 * min(observed), 1)),
        "arm_joints_valid_pct": {k: round(100 * joint_ok[k] / (2 * n_frames), 1) for k in ARM_JOINTS},
        "all_arm_joints_valid_pct": round(100 * arm_ok / n_frames, 1),
        "product_mask_iou": _iou_summary(iou_held, iou_rest, cover),
        "events": dict(total=n_events, agree_with_holding=agree),
    }


def to_markdown(q: Dict) -> str:
    k = q["task_kinds"]
    rows = [
        ("episodes", f"{q['episodes']} ({k['pass_']} hand-to-hand passes, {k['both_hands']} both-hands holds, "
                     f"{k['one_hand']} one hand: {', '.join(f'{v} {h}' for h, v in sorted(k['one_hand_by_hand'].items()))}"
                     + (f"; {k['repeated']} picked up twice" if k['repeated'] else "") + ")"),
        ("duration", f"{q['duration_s'][0]} to {q['duration_s'][1]} s per episode"),
        ("frames", f"{q['episode_frames']:,} episode frames from {q['unique_session_frames']:,} unique frames "
                   f"({q['unique_minutes']} min); episodes overlap"),
        ("hands observed (not interpolated)", f"{q['hands_observed_pct']['median_episode_hand']} % of frames "
                                              f"(median episode and hand; min {q['hands_observed_pct']['min']} %)"),
        ("arm joints measured (all frames)", ", ".join(f"{n} {v} %" for n, v in q["arm_joints_valid_pct"].items())
         + f"; all six at once {q['all_arm_joints_valid_pct']} %"),
        ("product pose vs. camera masks", (f"silhouette IoU median {q['product_mask_iou']['held_median']} while held, "
                                           f"{q['product_mask_iou']['rest_median']} while resting; "
                                           f"{q['product_mask_iou']['frames_iou_ge_0_5_pct']} % of frames with masks have IoU ≥ 0.5")
         if q["product_mask_iou"] else "not available in this release"),
        ("events agreeing with holding", f"{q['events']['agree_with_holding']} of {q['events']['total']} (±1 frame)"),
    ]
    return "| | |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)


def main(root: str, as_json: bool = False) -> str:
    q = summarize(root)
    return json.dumps(q, indent=1) if as_json else to_markdown(q)
