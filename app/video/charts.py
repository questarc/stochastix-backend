"""Chart images for the video, drawn with matplotlib in the app's dark-blue style."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402
from PIL import Image  # noqa: E402

PANEL = "#111e35"
TEXT = "#cbd5e1"
GRID = (0.58, 0.64, 0.72, 0.15)
BLUE, LIGHT, SKY, RED = "#60a5fa", "#93c5fd", "#3b82f6", "#f87171"
DPI = 100


def _money_axis(v, _):
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:.0f}"


def _figure(w: int, h: int, ncols: int = 1):
    fig, axes = plt.subplots(1, ncols, figsize=(w / DPI, h / DPI), dpi=DPI)
    fig.patch.set_facecolor(PANEL)
    for ax in np.atleast_1d(axes):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=TEXT, labelsize=13)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
    return fig, axes


def _to_image(fig) -> Image.Image:
    fig.tight_layout(pad=1.2)
    fig.canvas.draw()
    img = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert("RGB")
    plt.close(fig)
    return img.copy()


def fan_chart(result, retirement_age: int, w: int, h: int) -> Image.Image:
    fig, ax = _figure(w, h)
    ages, p = result.ages, result.percentiles
    ax.fill_between(ages, p[10], p[90], color=BLUE, alpha=0.16, linewidth=0, label="P10–P90")
    ax.fill_between(ages, p[25], p[75], color=BLUE, alpha=0.36, linewidth=0, label="P25–P75")
    ax.plot(ages, p[50], color=LIGHT, linewidth=3.2, label="Median")
    ax.axvline(retirement_age, color="#94a3b8", linestyle="--", linewidth=1.6)
    ax.text(retirement_age + 0.4, ax.get_ylim()[1] * 0.93, "Retirement", color=TEXT, fontsize=13)
    ax.yaxis.set_major_formatter(FuncFormatter(_money_axis))
    ax.set_xlabel("Age", color=TEXT, fontsize=13)
    ax.set_xlim(ages[0], ages[-1])
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", frameon=False, labelcolor=TEXT, fontsize=12)
    return _to_image(fig)


def allocation_chart(classes, current, model, highlight: str, w: int, h: int,
                     labels=("Current", "Model")) -> Image.Image:
    fig, ax = _figure(w, h)
    x = np.arange(len(classes))
    bars = ax.bar(x - 0.2, current, 0.38, color=SKY, label=labels[0])
    ax.bar(x + 0.2, model, 0.38, color=LIGHT, label=labels[1])
    for i, c in enumerate(classes):
        if c == highlight:
            bars[i].set_edgecolor("#fbbf24")
            bars[i].set_linewidth(2.5)
    for xi, v in zip(x - 0.2, current):
        ax.text(xi, v + 0.01, f"{v * 100:.0f}%", ha="center", color=TEXT, fontsize=12)
    ax.set_xticks(x, classes)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, labelcolor=TEXT, fontsize=13)
    return _to_image(fig)


def outcomes_chart(result, w: int, h: int) -> Image.Image:
    fig, (left, right) = _figure(w, h, ncols=2)
    counts, edges = np.histogram(result.ending_values, bins=60)
    left.bar((edges[:-1] + edges[1:]) / 2, counts, width=np.diff(edges) * 0.95, color=BLUE)
    left.xaxis.set_major_formatter(FuncFormatter(_money_axis))
    left.set_title("Ending value (nominal)", color=TEXT, fontsize=15)
    depl = result.depletion_ages
    right.set_title("Age when money runs out", color=TEXT, fontsize=15)
    if depl.size:
        ages, n = np.unique(depl, return_counts=True)
        right.bar(ages, n, color=RED)
        right.set_xlabel("Age", color=TEXT, fontsize=13)
    else:
        right.text(0.5, 0.5, "No scenarios ran out of money", ha="center", va="center",
                   color="#4ade80", fontsize=18, transform=right.transAxes)
        right.set_xticks([])
        right.set_yticks([])
    return _to_image(fig)


def indicator_chart(points: list[dict], kind: str, w: int, h: int) -> Image.Image:
    fig, ax = _figure(w, h)
    dates = [point["date"] for point in points]
    if kind == "rsi":
        ax.plot(dates, [point["rsi"] for point in points], color=LIGHT, linewidth=2.8, label="RSI (14)")
        ax.axhline(70, color="#fbbf24", linestyle="--", linewidth=1.5, label="Overbought reference")
        ax.axhline(30, color="#38bdf8", linestyle="--", linewidth=1.5, label="Oversold reference")
        ax.set_ylim(0, 100)
        ax.set_ylabel("RSI", color=TEXT)
    elif kind == "macd":
        macd = [point["macd"] for point in points]
        signal = [point["macd_signal"] for point in points]
        x = np.arange(len(points))
        ax.bar(x, np.asarray(macd) - np.asarray(signal), color="#64748b", alpha=0.65, label="Histogram")
        ax.plot(x, macd, color=LIGHT, linewidth=2.5, label="MACD")
        ax.plot(x, signal, color="#fbbf24", linewidth=2, label="Signal")
        ax.set_xticks(np.linspace(0, len(points) - 1, min(6, len(points)), dtype=int),
                      [dates[i] for i in np.linspace(0, len(points) - 1, min(6, len(points)), dtype=int)])
        ax.set_ylabel("MACD", color=TEXT)
    else:
        close = [point["close"] for point in points]
        ax.fill_between(dates, [point["bollinger_lower"] for point in points],
                        [point["bollinger_upper"] for point in points], color=BLUE, alpha=0.16,
                        label="Bollinger Bands")
        ax.plot(dates, close, color=LIGHT, linewidth=2.8, label="Close")
        ax.plot(dates, [point["bollinger_upper"] for point in points], color=BLUE, linewidth=1.2)
        ax.plot(dates, [point["bollinger_lower"] for point in points], color=BLUE, linewidth=1.2)
        ax.yaxis.set_major_formatter(FuncFormatter(_money_axis))
        ax.set_ylabel("Price", color=TEXT)
    if kind != "macd":
        step = max(1, len(points) // 6)
        ticks = list(range(0, len(points), step))
        if ticks[-1] != len(points) - 1:
            ticks.append(len(points) - 1)
        ax.set_xticks(ticks, [dates[i] for i in ticks])
    ax.tick_params(axis="x", labelrotation=0)
    ax.legend(loc="upper left", frameon=False, labelcolor=TEXT, fontsize=11)
    return _to_image(fig)
