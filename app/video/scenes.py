"""Draw each scene's content. ``t`` is seconds into the scene, used for entrance animations."""
from __future__ import annotations

from PIL import Image, ImageDraw

from . import charts
from .layout import ACCENT, CONTENT, MUTED, NEG, POS, TEXT, WHITE, font, panel, wrap_text
from .narration import Scene, money, pct

INTRO = 1.4  # seconds of entrance animation per scene


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _reveal(img: Image.Image, chart: Image.Image, xy, t: float) -> None:
    """Wipe a chart in from left to right."""
    k = ease(t / INTRO)
    cut = max(1, int(chart.width * k))
    img.paste(chart.crop((0, 0, cut, chart.height)), xy)


def draw_scene(img: Image.Image, scene: Scene, t: float, cache: dict) -> None:
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = CONTENT
    cw, ch = x1 - x0, y1 - y0
    data = scene.data
    if scene.kind == "title":
        k = ease(t / INTRO)
        d.text((x0, y0 + 40 - 20 * (1 - k)), data["client"], font=font(60, True), fill=WHITE)
        d.text((x0, y0 + 120), f"Retirement plan update  ·  {data['date']}", font=font(26), fill=ACCENT)
        n = len(data["facts"])
        gap, cardw = 24, (cw - 24 * (len(data["facts"]) - 1)) // n
        for i, (label, value) in enumerate(data["facts"]):
            if t < 0.25 * i:
                continue
            cx = x0 + i * (cardw + gap)
            panel(d, (cx, y0 + 220, cx + cardw, y0 + 360))
            d.text((cx + 24, y0 + 245), label, font=font(20), fill=MUTED)
            d.text((cx + 24, y0 + 285), value, font=font(40, True), fill=WHITE)
    elif scene.kind == "success":
        k = ease(t / INTRO)
        half = (cw - 40) // 2
        for i, (label, value, sub) in enumerate((
                ("Current portfolio", data["current"], f"{data['trials']:,} market scenarios"),
                (data["model_name"], data["model"], f"{data['delta_pp']:+.1f} percentage points vs current"))):
            bx = x0 + i * (half + 40)
            panel(d, (bx, y0 + 30, bx + half, y0 + 330))
            d.text((bx + 34, y0 + 60), label, font=font(24), fill=MUTED)
            d.text((bx + 34, y0 + 110), f"{value * k * 100:.1f}%", font=font(96, True), fill=WHITE)
            color = POS if (i == 1 and data["delta_pp"] > 0) else NEG if (i == 1 and data["delta_pp"] < 0) else MUTED
            d.text((bx + 34, y0 + 250), sub, font=font(22), fill=color)
            bar_w = half - 68
            d.rounded_rectangle((bx + 34, y0 + 292, bx + 34 + bar_w, y0 + 304), 6, fill=(34, 50, 79))
            d.rounded_rectangle((bx + 34, y0 + 292, bx + 34 + max(12, int(bar_w * value * k)), y0 + 304), 6, fill=ACCENT)
        d.text((x0, y0 + 365), "Probability of success = share of scenarios where the money lasts to the plan end age.",
               font=font(19), fill=MUTED)
    elif scene.kind in ("fan", "allocation", "outcomes"):
        if "chart" not in cache:
            if scene.kind == "fan":
                cache["chart"] = charts.fan_chart(data["result"], data["retirement_age"], cw, ch)
            elif scene.kind == "allocation":
                cache["chart"] = charts.allocation_chart(data["classes"], data["current"], data["model"],
                                                         data["highlight"], cw, ch)
            else:
                cache["chart"] = charts.outcomes_chart(data["result"], cw, ch)
        _reveal(img, cache["chart"], (x0, y0), t)
    elif scene.kind == "rebalance":
        p = data["proposal"]
        panel(d, (x0, y0 + 10, x0 + 560, y1 - 10))
        d.text((x0 + 30, y0 + 36), "Proposed trades", font=font(24, True), fill=WHITE)
        rows = [(tr.side, tr.ticker, money(tr.value)) for tr in p.trades][:7] or [("—", "No trades needed", "")]
        for i, (side, ticker, value) in enumerate(rows):
            if t < 0.15 * i:
                continue
            y = y0 + 90 + i * 40
            d.text((x0 + 30, y), side, font=font(22, True), fill=NEG if side == "Sell" else POS if side == "Buy" else MUTED)
            d.text((x0 + 130, y), ticker, font=font(22), fill=TEXT)
            d.text((x0 + 530, y), value, font=font(22), fill=TEXT, anchor="ra")
        rx = x0 + 600
        panel(d, (rx, y0 + 10, x1, y1 - 10))
        d.text((rx + 30, y0 + 36), "Probability of success", font=font(24, True), fill=WHITE)
        d.text((rx + 30, y0 + 100), "Before", font=font(22), fill=MUTED)
        d.text((rx + 30, y0 + 130), pct(data["before"]), font=font(64, True), fill=WHITE)
        k = ease((t - 0.6) / INTRO)
        d.text((rx + 30, y0 + 230), "After trades", font=font(22), fill=MUTED)
        after = data["before"] + (data["after"] - data["before"]) * k
        d.text((rx + 30, y0 + 260), f"{after * 100:.1f}%", font=font(64, True), fill=POS if data["after"] >= data["before"] else NEG)
        wrap_text(d, (rx + 30, y0 + 360), f"Sells {money(p.total_sells)} fund buys {money(p.total_buys)}. "
                  "Orders stay pending until approved.", 19, MUTED, 48)
    elif scene.kind == "closing":
        d.text((x0, y0 + 30), "Next steps", font=font(48, True), fill=WHITE)
        steps = ["Review this update at your convenience", "Reply with any questions or changes to your plan",
                 "We'll confirm any trades with you before they are placed"]
        for i, s in enumerate(steps):
            if t >= 0.35 * i:
                d.ellipse((x0, y0 + 128 + i * 60, x0 + 18, y0 + 146 + i * 60), fill=ACCENT)
                d.text((x0 + 36, y0 + 122 + i * 60), s, font=font(26), fill=TEXT)
        panel(d, (x0, y0 + 320, x1, y0 + 410), accent=False)
        wrap_text(d, (x0 + 26, y0 + 340), "These results are projections, not guarantees, and not investment "
                  "advice. They depend on capital market assumptions and do not include taxes or fees.", 19, MUTED, 105)
