"""Animated illustrated advisor. Pre-rendered at several mouth openings, with eyes open and closed."""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

MOUTH_LEVELS = 6
SS = 4  # supersampling for smooth edges

SKIN, SKIN_SHADE = (233, 196, 170), (214, 172, 146)
HAIR = (52, 40, 36)
SUIT, SHIRT, TIE = (30, 58, 138), (241, 245, 249), (96, 165, 250)


def _draw(size: int, mouth: float, blink: bool) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 100.0  # 100-unit design grid

    def box(x0, y0, x1, y1):
        return [x0 * u, y0 * u, x1 * u, y1 * u]

    # shoulders and suit
    d.ellipse(box(14, 72, 86, 130), fill=SUIT)
    d.polygon([(42 * u, 72 * u), (58 * u, 72 * u), (50 * u, 90 * u)], fill=SHIRT)
    d.polygon([(47.5 * u, 74 * u), (52.5 * u, 74 * u), (54 * u, 92 * u), (50 * u, 97 * u), (46 * u, 92 * u)], fill=TIE)
    d.polygon([(36 * u, 74 * u), (47 * u, 74 * u), (50 * u, 92 * u)], fill=(23, 45, 110))
    d.polygon([(64 * u, 74 * u), (53 * u, 74 * u), (50 * u, 92 * u)], fill=(23, 45, 110))
    # neck, ears, head
    d.rectangle(box(44, 60, 56, 75), fill=SKIN_SHADE)
    d.ellipse(box(25, 36, 33, 50), fill=SKIN_SHADE)
    d.ellipse(box(67, 36, 75, 50), fill=SKIN_SHADE)
    d.ellipse(box(29, 16, 71, 66), fill=SKIN)
    # hair
    d.pieslice(box(27, 11, 73, 50), 180, 360, fill=HAIR)
    d.ellipse(box(27, 20, 36, 40), fill=HAIR)
    d.ellipse(box(64, 20, 73, 40), fill=HAIR)
    d.polygon([(34 * u, 28 * u), (60 * u, 22 * u), (66 * u, 30 * u)], fill=HAIR)
    # eyebrows and eyes
    d.line(box(36, 34, 45, 33), fill=HAIR, width=int(1.6 * u))
    d.line(box(55, 33, 64, 34), fill=HAIR, width=int(1.6 * u))
    for cx in (40.5, 59.5):
        if blink:
            d.line(box(cx - 3.5, 40, cx + 3.5, 40), fill=(40, 30, 28), width=int(1.2 * u))
        else:
            d.ellipse(box(cx - 3.6, 37, cx + 3.6, 43), fill=(255, 255, 255))
            d.ellipse(box(cx - 2, 38, cx + 2, 42), fill=(45, 70, 110))
            d.ellipse(box(cx - 0.6, 38.6, cx + 0.6, 39.8), fill=(255, 255, 255))
    # nose and mouth
    d.line([(50 * u, 42 * u), (48 * u, 50 * u), (51 * u, 51 * u)], fill=SKIN_SHADE, width=int(1.1 * u))
    open_h = 0.6 + 6.0 * mouth
    if mouth < 0.08:
        d.arc(box(43, 52, 57, 58), 15, 165, fill=(150, 70, 70), width=int(1.3 * u))
    else:
        d.ellipse(box(44, 55 - open_h / 3, 56, 55 + open_h), fill=(120, 40, 50))
        d.rectangle(box(45.5, 55 - open_h / 3, 54.5, 55 - open_h / 3 + 1.4), fill=(245, 245, 245))
    return img.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=4)
def avatar_frames(size: int) -> dict[tuple[int, bool], Image.Image]:
    """{(mouth_level, blink): RGBA image} — chosen per frame from the narration loudness."""
    return {(m, b): _draw(size, m / (MOUTH_LEVELS - 1), b) for m in range(MOUTH_LEVELS) for b in (False, True)}


def avatar_badge(size: int, level: int, blink: bool, glow: float) -> Image.Image:
    """Avatar inside a circular badge with a glow ring that pulses while speaking."""
    pad = 14
    total = size + pad * 2
    out = Image.new("RGBA", (total, total), (0, 0, 0, 0))
    ring = Image.new("RGBA", (total, total), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    alpha = int(70 + 150 * glow)
    rd.ellipse([3, 3, total - 4, total - 4], outline=(96, 165, 250, alpha), width=6)
    out.alpha_composite(ring.filter(ImageFilter.GaussianBlur(4)))
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse([0, 0, size - 1, size - 1], fill=(22, 36, 63, 255))
    face = avatar_frames(size)[(level, blink)]
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    disc.paste(face, (0, 0), Image.composite(face.getchannel("A"), Image.new("L", (size, size), 0), mask))
    out.alpha_composite(disc, (pad, pad))
    ImageDraw.Draw(out).ellipse([pad - 2, pad - 2, pad + size + 1, pad + size + 1], outline=(147, 197, 253, 255), width=3)
    return out
