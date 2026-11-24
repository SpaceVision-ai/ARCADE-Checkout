"""Episode card: one figure with an episode's hand-to-product distances, product height and state,
and the holding lanes with grasp/release events (requires the ``viz`` extra: matplotlib).

    arcade-human overview RELEASE EPISODE_ID card.png

For 3-D renders and videos see ``arcade_human.render``; for the interactive viewer ``arcade_human.viewer``.
"""
from __future__ import annotations

import numpy as np

from .reader import Episode
from .style import PALETTE as COL, matplotlib_style


def _runs(v, t, fps):
    out, k, n = [], 0, len(v)
    while k < n:
        if v[k]:
            j = k
            while j < n and v[j]:
                j += 1
            out.append((t[k], (j - k) / fps))
            k = j
        else:
            k += 1
    return out


def plot_overview(ep: Episode, out: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    plt.rcParams.update(matplotlib_style())
    plt.rcParams.update({"font.size": 13})
    fps = float(ep.attrs.get("fps", 19.94))
    n = len(ep)
    t = np.arange(n) / fps
    op = ep.object_pose[:, :3].astype(np.float64)
    iou = ep["object/mask_iou"].astype(np.float64) if "object/mask_iou" in ep.data else None
    hold = {s: ep[f"interaction/{s}/holding"].astype(bool) for s in ("left", "right")}
    fig, axs = plt.subplots(3, 1, figsize=(12, 8.8), sharex=True, gridspec_kw=dict(height_ratios=[2.2, 1.7, 1.3]))

    # 1. palm-to-product distance, holding intervals shaded
    ax = axs[0]
    top = 1.0
    for s in ("left", "right"):
        h = ep.hand_position(s)[:, [0, 5, 9, 17]].astype(np.float64)
        palm = np.nanmean(h, axis=1) if np.isfinite(h).any() else np.full((n, 3), np.nan)
        d = np.linalg.norm(palm - op, axis=1) * 100
        if np.isfinite(d).any():
            top = max(top, float(np.nanmax(d)) * 1.05)
        ax.plot(t, d, color=COL[s], lw=2.2, label=f"{s} palm")
    for s in ("left", "right"):
        ax.fill_between(t, 0, top, where=hold[s], color=COL[s], alpha=0.12, step="mid", linewidth=0)
    ax.set_ylim(0, top)
    ax.set_ylabel("palm → product (cm)")
    ax.legend(handles=[Line2D([], [], color=COL["left"], lw=2.2, label="left palm"),
                       Line2D([], [], color=COL["right"], lw=2.2, label="right palm"),
                       Patch(color=COL["mute"], alpha=0.25, label="shaded: that hand holds the product")],
              loc="lower right", bbox_to_anchor=(1.0, 0.98), frameon=False, fontsize=11, ncol=3)

    # 2. product height, coloured by who holds it
    ax = axs[1]
    both = hold["left"] & hold["right"]
    groups = [("resting", ~hold["left"] & ~hold["right"], COL["rest"], "o"),
              ("held left", hold["left"] & ~hold["right"], COL["left"], "o"),
              ("held right", hold["right"] & ~hold["left"], COL["right"], "o"),
              ("held by both hands", both, COL["ink"], "D")]
    for label, m, c, mk in groups:
        if m.any():
            ax.scatter(t[m], op[m, 2] * 100, s=12 if mk == "o" else 10, color=c, marker=mk, zorder=3, label=label)
    ax.set_ylabel("product z (cm)")
    if iou is not None:
        ax2 = ax.twinx()
        ax2.plot(t, iou, color=COL["mute"], lw=1.2, alpha=0.8)
        ax2.set_ylim(0, 1.05)
        ax2.set_ylabel("mask IoU", color=COL["mute"])
        ax2.spines["right"].set_visible(True)
        ax.plot([], [], color=COL["mute"], lw=1.2, label="pose vs. camera masks (IoU, right axis)")
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.98), frameon=False, fontsize=11, ncol=5, markerscale=1.4,
              columnspacing=1.0, handletextpad=0.3)

    # 3. holding lanes (solid) with the 2-D HOI label (thin), and the events
    ax = axs[2]
    for i, s in enumerate(("left", "right")):
        y = 1 - i
        ax.broken_barh([(0, t[-1])], (y - 0.18, 0.36), color=COL["track"])
        ax.broken_barh(_runs(hold[s], t, fps), (y - 0.18, 0.36), color=COL[s])
        ax.broken_barh(_runs(ep[f"interaction/{s}/hoi_holding"].astype(bool), t, fps), (y - 0.36, 0.1),
                       color=COL[s], alpha=0.4)
        ax.text(-0.01, y, f"{s} hand", transform=ax.get_yaxis_transform(), ha="right", va="center", color=COL["mute"])
    for e in ep.events:
        y = 1 if e["hand"] == "left" else 0
        ax.scatter([e["frame"] / fps], [y + 0.34], marker="v", s=70, edgecolors=COL[e["hand"]], linewidths=1.5,
                   facecolors=COL[e["hand"]] if e["kind"] == "grasp" else "white", zorder=5)
    ax.set_yticks([])
    ax.set_ylim(-0.6, 1.6)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("time (s)")
    ax.legend(handles=[Line2D([], [], marker="v", ls="", color=COL["ink"], markersize=8, label="grasp"),
                       Line2D([], [], marker="v", ls="", markerfacecolor="white", markeredgecolor=COL["ink"],
                              markersize=8, label="release"),
                       Patch(color=COL["mute"], label="holding"),
                       Patch(color=COL["mute"], alpha=0.4, label="2-D HOI label (thin)")],
              loc="lower right", frameon=False, fontsize=11, ncol=4, bbox_to_anchor=(1.0, 0.98))

    fig.suptitle(f"{ep.episode_id} · {ep.product}\n{ep.task}", x=0.01, ha="left", fontsize=14,
                 fontweight="bold", color=COL["ink"])
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor="white")
    plt.close(fig)
    return out
