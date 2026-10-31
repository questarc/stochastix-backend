"""Frame layout: background, header, scene content area and the advisor bar along the bottom."""
from __future__ import annotations

import textwrap
from functools import lru_cache
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
CONTENT = (60, 100, 1220, 528)        # x0, y0, x1, y1 of the scene area
BAR_Y = 548                           # top of the advisor bar
AVATAR = 128
TEXT, MUTED, ACCENT, WHITE = (226, 232, 240), (159, 178, 207), (96, 165, 250), (255, 255, 255)
POS, NEG, WARN = (74, 222, 128), (248, 113, 113), (251, 191, 36)

_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"


@lru_cache(maxsize=32)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


@lru_cache(maxsize=1)
def background() -> Image.Image:
    """Navy background with soft blue glows, like the app."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.array([10, 18, 32], np.float32)
    img = np.broadcast_to(base, (H, W, 3)).copy()
    for cx, cy, r, color, strength in ((0, -70, 900, (37, 99, 235), 0.32), (W, 0, 760, (14, 165, 233), 0.18),
                                       (W / 2, H + 80, 700, (30, 58, 138), 0.35)):
        g = np.clip(1 - np.hypot(x - cx, y - cy) / r, 0, 1) ** 2 * strength
        img += g[..., None] * (np.array(color, np.float32) - img)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def panel(draw: ImageDraw.ImageDraw, box, radius: int = 18, accent: bool = True) -> None:
    draw.rounded_rectangle(box, radius, fill=(17, 30, 53), outline=(52, 73, 110), width=2)
    if accent:
        x0, y0, x1, _ = box
        draw.rounded_rectangle((x0 + 2, y0, x1 - 2, y0 + 4), 2, fill=ACCENT)


def header(img: Image.Image, title: str, client: str, scene_no: int, scenes: int) -> None:
    d = ImageDraw.Draw(img)
    d.text((60, 30), title, font=font(36, True), fill=(219, 234, 254))
    right = f"{client}  ·  {scene_no}/{scenes}"
    d.text((W - 60, 40), right, font=font(20), fill=MUTED, anchor="ra")
    d.line((60, 84, W - 60, 84), fill=(52, 73, 110), width=2)


def advisor_bar(img: Image.Image, advisor: str) -> None:
    """Static part of the bottom bar; the avatar and subtitles are added per frame."""
    overlay = Image.new("RGBA", (W, H - BAR_Y), (8, 16, 30, 225))
    img.paste(overlay, (0, BAR_Y), overlay)
    d = ImageDraw.Draw(img)
    d.line((0, BAR_Y, W, BAR_Y), fill=ACCENT, width=2)
    d.text((40 + AVATAR + 28 + 30, BAR_Y + 18), advisor, font=font(22, True), fill=WHITE)
    d.text((40 + AVATAR + 28 + 30, BAR_Y + 46), "Your financial advisor  ·  Stochastix AI", font=font(16), fill=MUTED)


SUB_X = 40 + AVATAR + 58
SUB_W = W - SUB_X - 50


@lru_cache(maxsize=256)
def subtitle_image(text: str) -> Image.Image:
    img = Image.new("RGBA", (SUB_W, 96), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lines = textwrap.wrap(text, width=68)[:2]
    for i, line in enumerate(lines):
        d.text((0, 6 + i * 36), line, font=font(25), fill=TEXT)
    return img


def progress_bar(img: Image.Image, fraction: float) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle((0, H - 5, W, H), fill=(22, 36, 63))
    d.rectangle((0, H - 5, int(W * fraction), H), fill=ACCENT)


def wrap_text(draw, xy, text: str, size: int, fill, width_chars: int, bold: bool = False, spacing: int = 10) -> int:
    x, y = xy
    for line in textwrap.wrap(text, width=width_chars):
        draw.text((x, y), line, font=font(size, bold), fill=fill)
        y += size + spacing
    return y
