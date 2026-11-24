"""Leakage-aware train / val / test splits.

Episodes come from one continuous session and overlap in time: each episode carries lead-in and
tail context, and with two hands the shopper can handle one product while another is still being
put down. 17,201 episode frames cover 8,969 unique session frames. A random split by episode would
therefore put the same motion in train and test.

    from arcade_human import ArcadeHuman
    from arcade_human.splits import time_split, product_split
    s = time_split(ArcadeHuman(root))            # {'train': [...], 'val': [...], 'test': [...], 'boundary': [...]}
    s = product_split(ArcadeHuman(root), "mesil")   # unseen product; overlapping train episodes dropped
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from .reader import ArcadeHuman


def time_split(ds: ArcadeHuman, fractions: Sequence[float] = (0.8, 0.1, 0.1),
               names: Sequence[str] = ("train", "val", "test")) -> Dict[str, List[str]]:
    """Cut the session timeline into contiguous blocks (by fraction of session frames covered).

    An episode goes to the block that contains it entirely; episodes that straddle a block boundary
    are returned under 'boundary' and are best left out of evaluation. No frame of a train episode
    appears in a val/test episode.
    """
    assert len(fractions) == len(names) and abs(sum(fractions) - 1.0) < 1e-6
    rows = sorted(ds.index, key=lambda r: r["source_frame_range"][0])
    t0 = min(r["source_frame_range"][0] for r in rows)
    t1 = max(r["source_frame_range"][1] for r in rows)
    cuts, acc = [], t0
    for f in fractions[:-1]:
        acc += f * (t1 - t0 + 1)
        cuts.append(acc)
    bounds = [t0] + cuts + [t1 + 1]
    out: Dict[str, List[str]] = {n: [] for n in names}
    out["boundary"] = []
    for r in rows:
        a, b = r["source_frame_range"]
        for i, n in enumerate(names):
            if bounds[i] <= a and b < bounds[i + 1]:
                out[n].append(r["episode_id"])
                break
        else:
            out["boundary"].append(r["episode_id"])
    return out


def product_split(ds: ArcadeHuman, held_out: str, drop_overlapping: bool = True) -> Dict[str, List[str]]:
    """Episodes of one product as 'test', the rest as 'train'.

    Tests generalisation to an unseen product shape and appearance. Episodes of other products often
    share session frames with the test episodes (the shopper puts one product down while picking up
    the next). With ``drop_overlapping`` (default) those train episodes are left out ('dropped'), so
    no frame is shared; with False they stay in train and the shopper's motion leaks into test.
    """
    if held_out not in ds.products:
        raise KeyError(f"unknown product {held_out!r}; choose from {sorted(ds.products)}")
    test = [r for r in ds.index if r["product"] == held_out]
    rest = [r for r in ds.index if r["product"] != held_out]
    if not drop_overlapping:
        return dict(train=[r["episode_id"] for r in rest], test=[r["episode_id"] for r in test])
    spans = [r["source_frame_range"] for r in test]

    def overlaps(r):
        a, b = r["source_frame_range"]
        return any(a <= y and x <= b for x, y in spans)
    return dict(train=[r["episode_id"] for r in rest if not overlaps(r)], test=[r["episode_id"] for r in test],
                dropped=[r["episode_id"] for r in rest if overlaps(r)])


def overlap_report(ds: ArcadeHuman) -> Dict[str, float]:
    """How much episodes overlap: total episode frames vs unique session frames."""
    frames = set()
    total = 0
    for r in ds.index:
        a, b = r["source_frame_range"]
        frames.update(range(a, b + 1))
        total += b - a + 1
    fps = float(ds.info.get("fps", 19.94))
    return dict(episode_frames=total, unique_session_frames=len(frames), unique_minutes=round(len(frames) / fps / 60, 2))
