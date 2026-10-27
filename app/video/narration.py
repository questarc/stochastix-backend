"""Scene list and narration for the investor video. Fixed templates filled only with engine results."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ..voice.script import DISCLAIMER


@dataclass
class Scene:
    kind: str           # title | success | fan | allocation | outcomes | rebalance | closing
    title: str
    narration: str      # display form (shown as subtitles); spoken form comes from voice.script.speakable
    data: dict = field(default_factory=dict)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def money(x: float) -> str:
    return f"${x:,.0f}"


def build_scenes(portfolio, current, model, plan: dict, proposal=None, success_after: float | None = None,
                 today: date | None = None) -> list[Scene]:
    """``current``/``model`` are engine SimulationResults; ``plan`` holds the effective ages and cash flows."""
    a = portfolio.account
    first = a.client_name.split()[0]
    today = today or date.today()
    trials = current.settings["trials"]
    cur_p, mod_p = current.success_probability, model.success_probability
    delta = (mod_p - cur_p) * 100
    ret, end = plan["retirement_age"], plan["plan_end_age"]
    ages = list(current.ages)
    p50_ret = float(current.percentiles[50][ages.index(ret)]) if ret in ages else float(current.percentiles[50][0])
    median_real = float(np.median(current.ending_values_real))
    scenes = [
        Scene("title", f"Retirement plan update", (
            f"Hello {first}. This is {a.advisor} with your retirement plan update. "
            f"Here is where your plan stands today."), {
            "client": a.client_name, "date": today.strftime("%B %d, %Y").replace(" 0", " "),
            "facts": [("Portfolio value", money(portfolio.market_value)), ("Age today", str(a.age)),
                      ("Retire at", str(ret)), ("Plan to age", str(end))]}),
        Scene("success", "Probability of success", (
            f"We tested your plan against {trials:,} possible market futures. With your current portfolio, "
            f"your money lasts to age {end} in {pct(cur_p)} of them. With the {portfolio.model.model_name} "
            f"model portfolio, that becomes {pct(mod_p)}, {delta:+.1f} pp."), {
            "current": cur_p, "model": mod_p, "delta_pp": delta, "model_name": portfolio.model.model_name,
            "trials": trials}),
        Scene("fan", "Projected portfolio value", (
            f"This chart shows the range of outcomes by age. The bright line is the middle outcome. "
            f"At your retirement at age {ret}, the median projection is {money(p50_ret)}. "
            f"At age {end}, the median value in today's dollars is {money(median_real)}."), {
            "result": current, "retirement_age": ret}),
    ]
    weights = portfolio.current_weights
    classes = list(dict.fromkeys(list(portfolio.model.weights) + list(weights)))
    drift = {ac: weights.get(ac, 0.0) - portfolio.model.weights.get(ac, 0.0) for ac in classes}
    top = max(drift, key=lambda k: abs(drift[k]))
    scenes.append(Scene("allocation", "Current vs model allocation", (
        f"Your largest difference from the model is {top}: {pct(weights.get(top, 0.0))} today, "
        f"compared with a target of {pct(portfolio.model.weights.get(top, 0.0))}."), {
        "classes": classes, "current": [weights.get(c, 0.0) for c in classes],
        "model": [portfolio.model.weights.get(c, 0.0) for c in classes], "highlight": top}))
    depl = current.depletion_ages
    if depl.size:
        outcome = (f"In {pct(depl.size / trials)} of the scenarios the money runs out, most often around "
                   f"age {np.median(depl):.0f}. The earliest is age {int(depl.min())}.")
    else:
        outcome = "In none of the scenarios did the money run out before the end of the plan."
    scenes.append(Scene("outcomes", "Range of outcomes", outcome, {"result": current}))
    if proposal is not None:
        if proposal.trades:
            text = (f"To bring your portfolio back to the model, we propose selling {money(proposal.total_sells)} "
                    f"and buying {money(proposal.total_buys)}, with no new cash needed. This moves your "
                    f"probability of success from {pct(cur_p)} to {pct(success_after if success_after is not None else cur_p)}.")
        else:
            text = "Your portfolio is within its tolerance of the model, so no trades are needed right now."
        scenes.append(Scene("rebalance", "Proposed rebalance", text, {
            "proposal": proposal, "before": cur_p, "after": success_after if success_after is not None else cur_p}))
    scenes.append(Scene("closing", "Next steps", (
        f"I'd be glad to walk through this with you at your convenience. Just reply with any questions. "
        f"{DISCLAIMER}"), {"advisor": a.advisor, "client": a.client_name}))
    return scenes
