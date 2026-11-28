"""One visual style for every ARCADE figure, render and viewer: colours, fonts and 2-D overlays.

Blue is always the left hand and orange the right hand (Tableau-10 C0/C1, colour-blind safe);
everything else is neutral grey. Importing this module needs only the standard library; the
drawing helpers import Pillow when called.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

PALETTE: Dict[str, str] = {
    "left": "#1F77B4",          # left hand
    "right": "#FF7F0E",         # right hand
    "body": "#AEB7C3",          # shopper mannequin
    "ink": "#1F2328",           # text
    "mute": "#6B7280",          # secondary text, axes
    "track": "#E3E6EA",         # empty timeline lane
    "panel": "#F6F7F9",         # strip / card background
    "chip": "#FFFFFF",          # label chips
    "rest": "#AEB2B9",          # product resting on the counter
    "counter_top": "#E4E0D8",
    "counter_body": "#BCC1C8",
}
SIDES = ("left", "right")

#: first existing file wins; set ARCADE_FONT / ARCADE_FONT_BOLD to use your own
FONT_CANDIDATES = {
    False: (os.environ.get("ARCADE_FONT", ""), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf"),
    True: (os.environ.get("ARCADE_FONT_BOLD", ""), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/Library/Fonts/Arial Bold.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "C:/Windows/Fonts/arialbd.ttf"),
}


def hex_rgb(h: str) -> List[float]:
    """'#RRGGBB' -> [r, g, b] in 0..1."""
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def hex_rgb255(h: str) -> Tuple[int, int, int]:
    """'#RRGGBB' -> (r, g, b) in 0..255."""
    return tuple(int(round(255 * c)) for c in hex_rgb(h))


def font(size: int, bold: bool = False):
    from PIL import ImageFont
    for p in FONT_CANDIDATES[bold]:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, int(size))
    return ImageFont.load_default()


def fit_font(draw, text: str, max_width: float, size: int, bold: bool = False, min_size: int = 10):
    """The largest font up to `size` that fits `text` into `max_width` pixels."""
    while size > min_size and draw.textlength(text, font=font(size, bold)) > max_width:
        size -= 1
    return font(size, bold)


def chip(img, xy: Tuple[int, int], text: str, size: int = 26, bold: bool = True, alpha: int = 225):
    """A rounded white label drawn on a PIL image in place."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img, "RGBA")
    f = font(size, bold)
    pad = int(round(size * 0.6))
    w = int(d.textlength(text, font=f)) + 2 * pad
    h = int(round(size * 1.75))
    x, y = xy
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=hex_rgb255(PALETTE["chip"]) + (alpha,))
    d.text((x + pad, y + h // 2), text, fill=hex_rgb255(PALETTE["ink"]), font=f, anchor="lm")
    return img


def _runs(mask: Sequence[bool]):
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            yield i, j
            i = j
        else:
            i += 1


def _overlay_rect(im, box, rgba):
    from PIL import Image, ImageDraw
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rectangle(box, fill=rgba)
    im.paste(Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB"))


def strip(width: int, height: int, n: int, t: int, holding: Dict[str, Sequence[bool]], events: Sequence[Dict],
          fps: float, title: str = "", shade: Optional[Sequence[bool]] = None, shade_label: str = ""):
    """The timeline strip under every ARCADE video: the task, one lane per hand (filled while that hand
    holds the product), grasp (filled) / release (outlined) markers, and a time cursor. Frames in
    `shade` get a grey band across both lanes, explained by `shade_label` in the legend.

    Designed at 1920 x 200 px; other sizes scale with the width.
    """
    from PIL import Image, ImageDraw
    s = width / 1920.0
    im = Image.new("RGB", (width, height), hex_rgb255(PALETTE["panel"]))
    d = ImageDraw.Draw(im)
    ink, mute, track = hex_rgb255(PALETTE["ink"]), hex_rgb255(PALETTE["mute"]), hex_rgb255(PALETTE["track"])
    m = 40 * s
    clock = f"{t / fps:4.1f} s / {(n - 1) / fps:.1f} s"
    fc = font(28 * s)
    d.text((width - m, 34 * s), clock, fill=ink, font=fc, anchor="rm")
    if title:
        room = width - 2 * m - d.textlength("00.0 s / 00.0 s", font=fc) - 40 * s
        d.text((m, 34 * s), title, fill=ink, font=fit_font(d, title, room, int(30 * s), bold=True), anchor="lm")
    x0, x1 = 210 * s, width - m
    lanes = {"left": 98 * s, "right": 150 * s}
    r = 9 * s
    for side, y in lanes.items():
        d.text((x0 - 20 * s, y), f"{side} hand", fill=mute, font=font(24 * s), anchor="rm")
        d.rounded_rectangle([x0, y - r, x1, y + r], radius=r, fill=track)
        for i, j in _runs(holding[side]):
            d.rounded_rectangle([x0 + (x1 - x0) * i / n, y - r, x0 + (x1 - x0) * j / n, y + r], radius=r,
                                fill=hex_rgb255(PALETTE[side]))
    if shade is not None:
        for i, j in _runs(shade):
            _overlay_rect(im, [x0 + (x1 - x0) * i / n, lanes["left"] - r - 8 * s, x0 + (x1 - x0) * j / n,
                               lanes["right"] + r + 8 * s], mute + (70,))
        d = ImageDraw.Draw(im)
    for e in events:
        x, y = x0 + (x1 - x0) * e["frame"] / n, lanes[e["hand"]]
        col = hex_rgb255(PALETTE[e["hand"]])
        tri = [(x - 12 * s, y - 30 * s), (x + 12 * s, y - 30 * s), (x, y - 12 * s)]
        d.polygon(tri, fill=col if e["kind"] == "grasp" else hex_rgb255(PALETTE["panel"]), outline=col,
                  width=max(1, int(round(3 * s))))
    xc = x0 + (x1 - x0) * t / max(n - 1, 1)
    d.line([xc, 66 * s, xc, height - 14 * s], fill=ink, width=max(1, int(round(3 * s))))
    yl = height - 18 * s
    fl = font(24 * s)
    d.polygon([(x0, yl - 8 * s), (x0 + 20 * s, yl - 8 * s), (x0 + 10 * s, yl + 8 * s)], fill=ink)
    d.text((x0 + 28 * s, yl), "grasp", fill=mute, font=fl, anchor="lm")
    x2 = x0 + 28 * s + d.textlength("grasp", font=fl) + 30 * s
    d.polygon([(x2, yl - 8 * s), (x2 + 20 * s, yl - 8 * s), (x2 + 10 * s, yl + 8 * s)], outline=ink,
              width=max(1, int(round(2 * s))))
    d.text((x2 + 28 * s, yl), "release", fill=mute, font=fl, anchor="lm")
    if shade is not None and shade_label:
        x3 = x2 + 28 * s + d.textlength("release", font=fl) + 30 * s
        _overlay_rect(im, [x3, yl - 9 * s, x3 + 22 * s, yl + 9 * s], mute + (70,))
        ImageDraw.Draw(im).text((x3 + 30 * s, yl), shade_label, fill=mute, font=fl, anchor="lm")
    return im


def matplotlib_style() -> Dict:
    """rcParams for matplotlib figures in the same style."""
    return {"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": PALETTE["mute"],
            "axes.labelcolor": PALETTE["ink"], "xtick.color": PALETTE["mute"], "ytick.color": PALETTE["mute"],
            "axes.spines.top": False, "axes.spines.right": False, "text.color": PALETTE["ink"]}


def side_rgb255(side: str) -> Tuple[int, int, int]:
    return hex_rgb255(PALETTE[side])


def body_rgb255(alpha: Optional[int] = None):
    c = hex_rgb255(PALETTE["body"])
    return c + ((alpha,) if alpha is not None else ())
