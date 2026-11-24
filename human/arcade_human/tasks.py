"""Plain-language task of an episode, derived from its per-hand holding intervals.

Every episode is one of four kinds, decided by the handling in the episode's core window (the
lead-in and tail context can show the end or start of a neighbouring handling, which is ignored):

* ``one_hand``:   one hand picks the product up and puts it down;
* ``pass``:       both hands hold it and it ends in the other hand (a hand-to-hand pass);
* ``both_hands``: both hands hold it, then the hand that picked it up puts it down;
* ``repeated``:   the product is put down and picked up again within the core window.

    >>> task_sentence("cylinder", "left", "right", both_hands=True)
    'Pick up the bottle from the checkout counter with the left hand, pass it to the right hand, and put it down.'
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence, Tuple

OBJECT_WORD = {"cylinder": "bottle", "box": "box"}
KINDS = ("one_hand", "pass", "both_hands", "repeated")


def hands_order(events: Iterable[Dict]) -> Tuple[Optional[str], Optional[str], Tuple[str, ...]]:
    """(hand of the first grasp, hand of the last release, hands that grasp) from a list of events with
    'frame', 'hand' and 'kind'. Ties keep the event order."""
    ev = list(events)
    grasps = [e for e in ev if e["kind"] == "grasp"]
    releases = [e for e in ev if e["kind"] == "release"]
    first = min(grasps, key=lambda e: e["frame"])["hand"] if grasps else None
    last = None
    for e in releases:                       # the latest release; on a tie the later-listed one
        if last is None or e["frame"] >= last["frame"]:
            last = e
    hands = tuple(sorted({e["hand"] for e in grasps}))
    return first, (last["hand"] if last else first), hands


def core_handling(holding: Dict[str, Sequence[bool]], core: Tuple[int, int], gap: int = 3):
    """(kind, first hand, last hand) of the handling in the core window [core[0], core[1]) from per-hand
    holding arrays (same frame indexing).

    Holding intervals of both hands are merged into runs (gaps up to `gap` frames bridged). A run belongs to
    the core window when at least half of it lies inside; if none does, the run with the largest overlap is
    used. The first hand is the one whose holding starts first in that run, the last hand the one whose
    holding ends last.
    """
    segs = []
    for side, h in holding.items():
        h = list(map(bool, h))
        i, n = 0, len(h)
        while i < n:
            if h[i]:
                j = i
                while j < n and h[j]:
                    j += 1
                segs.append((i, j, side))
                i = j
            else:
                i += 1
    if not segs:
        return "one_hand", None, None
    segs.sort()
    runs = []
    for a, b, side in segs:
        if runs and a <= runs[-1][1] + gap:
            runs[-1][1] = max(runs[-1][1], b)
            runs[-1][2].append((a, b, side))
        else:
            runs.append([a, b, [(a, b, side)]])
    a0, b0 = core
    ov = [max(0, min(r[1], b0) - max(r[0], a0)) for r in runs]
    core_runs = [r for r, o in zip(runs, ov) if o >= 0.5 * (r[1] - r[0])] or [runs[ov.index(max(ov))]]
    if len(core_runs) > 1:
        s = [x for r in core_runs for x in r[2]]
        return "repeated", min(s)[2], max(s, key=lambda x: (x[1], x[0]))[2]
    s = core_runs[0][2]
    first, last = min(s)[2], max(s, key=lambda x: (x[1], x[0]))[2]
    return kind_of(first, last, {x[2] for x in s}), first, last


def kind_of(first: Optional[str], last: Optional[str], hands: Iterable[str]) -> str:
    if len(set(hands)) < 2:
        return "one_hand"
    return "pass" if first != last else "both_hands"


def task_sentence(shape: str, first: Optional[str], last: Optional[str], both_hands: bool,
                  where: str = " from the checkout counter", repeated: bool = False) -> str:
    """The language task used by the ARCADE robot datasets."""
    obj = OBJECT_WORD.get(shape, "product")
    first = first or "right"
    if repeated:
        return f"Pick up the {obj}{where}, put it down, pick it up again, and put it down."
    if not both_hands:
        return f"Pick up the {obj}{where} with the {first} hand and put it down."
    if first != last:
        return f"Pick up the {obj}{where} with the {first} hand, pass it to the {last} hand, and put it down."
    return (f"Pick up the {obj}{where} with the {first} hand, hold it with both hands, "
            f"and put it down with the {first} hand.")
