"""LangChain tools for the Advisor AI. Every tool returns JSON; numbers are pre-formatted."""
from __future__ import annotations

import functools
import json
from typing import Literal

from langchain_core.tools import tool

from ..engine import CapitalMarketAssumptions
from ..methodology import find_section
from ..rebalance import RebalanceSettings, generate_orders, propose_rebalance
from ..services import (
    find_account_ids, find_source_for_account, load_account_portfolio,
    resolve_model_id, run_portfolio_simulation, summarize_result,
)


def pct(x: float | None) -> str | None:
    return None if x is None else f"{x * 100:.1f}%"


def money(x: float | None) -> str | None:
    return None if x is None else f"${x:,.0f}"


def _dumps(data) -> str:
    return json.dumps(data, default=str)


def _fmt_summary(s: dict) -> dict:
    return {
        "probability_of_success": pct(s["success_probability"]),
        "ending_value_median_P50_todays_dollars": money(s["median_ending_value_todays_dollars"]),
        "failed_trials": s["failed_trials"],
        "median_depletion_age": s["median_depletion_age"],
        "earliest_depletion_age": s["earliest_depletion_age"],
    }


def build_tools(sources: dict, cma: CapitalMarketAssumptions, rebalance_settings: RebalanceSettings,
                max_trials: int = 25_000) -> list:
    def _model_id(account_id: str, model_id: str | None) -> str | None:
        if not model_id:
            return None
        return resolve_model_id(find_source_for_account(sources, account_id), model_id)

    def _portfolio(account_id: str, model_id: str | None = None):
        return load_account_portfolio(sources, account_id, _model_id(account_id, model_id))

    def _sim(pf, weights, trials=10_000, seed=42, sampling="prng", copula="gaussian", **plan):
        return summarize_result(run_portfolio_simulation(
            pf, cma, weights, trials=min(int(trials), max_trials), seed=seed,
            sampling=sampling, copula=copula, **plan))

    def _rebalance(account_id: str, model_id: str | None, drift_tolerance: float | None):
        pf = _portfolio(account_id, model_id)
        settings = rebalance_settings.override(drift_tolerance=drift_tolerance)
        proposal = propose_rebalance(account_id, pf.positions, pf.model, settings)
        before = _sim(pf, pf.current_weights)["success_probability"]
        after = _sim(pf, proposal.post_trade_weights)["success_probability"] if proposal.trades else before
        return pf, proposal, before, after

    def _proposal_view(proposal, before, after) -> dict:
        return {
            "account_id": proposal.account_id, "model": proposal.model_name,
            "max_drift": pct(proposal.max_drift), "rebalance_needed": proposal.rebalance_needed,
            "trades": [{"side": t.side, "ticker": t.ticker, "asset_class": t.asset_class,
                        "quantity": t.quantity, "price": money(t.price), "value": money(t.value)}
                       for t in proposal.trades] or "none",
            "total_sells": money(proposal.total_sells), "total_buys": money(proposal.total_buys),
            "uninvested_cash": money(proposal.uninvested_cash),
            "allocation": [{"asset_class": r["asset_class"], "current": pct(r["current"]),
                            "model": pct(r["model"]), "after_trades": pct(r["post_trade"])}
                           for r in proposal.allocation],
            "probability_of_success_current": pct(before), "probability_of_success_after_trades": pct(after),
        }

    def safe(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # tools never raise into the agent
                return _dumps({"error": str(exc).strip("'\"")})
        return wrapper

    @tool
    @safe
    def list_accounts() -> str:
        """List every client account with its source, plan and assigned model."""
        return _dumps([{**a.to_dict(), "source": s.name} for s in sources.values() for a in s.list_accounts()])

    @tool
    @safe
    def list_model_portfolios() -> str:
        """List the model portfolios and their target asset-class weights."""
        seen, out = set(), []
        for s in sources.values():
            for m in s.list_model_portfolios():
                if m.model_id not in seen:
                    seen.add(m.model_id)
                    out.append({"model_id": m.model_id, "model_name": m.model_name,
                                "weights": {k: pct(v) for k, v in m.weights.items()}})
        return _dumps(out)

    @tool
    @safe
    def get_account_portfolio(account_id: str, model_id: str | None = None) -> str:
        """Get an account's plan, positions and allocation (current, model, drift)."""
        pf = _portfolio(account_id, model_id)
        classes = list(dict.fromkeys(list(pf.model.weights) + list(pf.current_weights)))
        return _dumps({
            "account": pf.account.to_dict(), "market_value": money(pf.market_value), "model": pf.model.model_name,
            "positions": [{"ticker": p.ticker, "asset_class": p.asset_class, "quantity": p.quantity,
                           "market_value": money(p.market_value)} for p in pf.positions],
            "allocation": [{"asset_class": ac, "current": pct(pf.current_weights.get(ac, 0.0)),
                            "model": pct(pf.model.weights.get(ac, 0.0)),
                            "drift": pct(pf.current_weights.get(ac, 0.0) - pf.model.weights.get(ac, 0.0))}
                           for ac in classes],
        })

    @tool
    @safe
    def run_simulation(account_id: str, portfolio: Literal["current", "model"] = "current",
                       model_id: str | None = None, retirement_age: int | None = None,
                       plan_end_age: int | None = None, annual_contribution: float | None = None,
                       annual_withdrawal: float | None = None, trials: int = 10_000, seed: int = 42,
                       sampling: Literal["prng", "lhs", "sobol"] = "prng",
                       copula: Literal["gaussian", "student_t"] = "gaussian") -> str:
        """Run a Monte Carlo simulation. Pass plan values only for what-if questions."""
        pf = _portfolio(account_id, model_id)
        weights = pf.current_weights if portfolio == "current" else pf.model.weights
        common = dict(trials=trials, seed=seed, sampling=sampling, copula=copula)
        plan = {k: v for k, v in dict(retirement_age=retirement_age, plan_end_age=plan_end_age,
                annual_contribution=annual_contribution, annual_withdrawal=annual_withdrawal).items() if v is not None}
        result = _sim(pf, weights, **common, **plan)
        out = {"account_id": account_id, "portfolio": portfolio, "result": _fmt_summary(result),
               "trials": min(int(trials), max_trials), "seed": seed}
        if plan:
            base = _sim(pf, weights, **common)
            out["what_if"] = plan
            out["saved_plan_baseline"] = _fmt_summary(base)
            out["difference_percentage_points"] = f"{(result['success_probability'] - base['success_probability']) * 100:+.1f}"
        return _dumps(out)

    @tool
    @safe
    def compare_current_vs_model(account_id: str, model_id: str | None = None) -> str:
        """Compare probability of success of the current portfolio with the model portfolio."""
        pf = _portfolio(account_id, model_id)
        cur, mod = _sim(pf, pf.current_weights), _sim(pf, pf.model.weights)
        diff = mod["success_probability"] - cur["success_probability"]
        higher = "model" if diff > 0 else "current" if diff < 0 else "equal"
        return _dumps({"account_id": account_id, "model": pf.model.model_name, "current": _fmt_summary(cur),
                       "model_portfolio": _fmt_summary(mod), "difference_percentage_points": f"{diff * 100:+.1f}",
                       "higher": higher})

    @tool("propose_rebalance")
    @safe
    def propose_rebalance_tool(account_id: str, model_id: str | None = None,
                               drift_tolerance: float | None = None) -> str:
        """Propose rebalancing trades and the probability of success before and after."""
        _, proposal, before, after = _rebalance(account_id, model_id, drift_tolerance)
        return _dumps(_proposal_view(proposal, before, after))

    @tool(response_format="content_and_artifact")
    def simulate_and_rebalance(account_ids: list[str] | None = None, client_name: str | None = None,
                               model_id: str | None = None, drift_tolerance: float | None = None):
        """Simulate and rebalance one or more accounts and create pending orders. Call once."""
        ids = list(account_ids or [])
        if client_name:
            ids += [i for i in find_account_ids(sources, client_name) if i not in ids]
        results, orders = [], []
        for account_id in ids:
            try:
                pf, proposal, before, after = _rebalance(account_id, model_id, drift_tolerance)
                new = generate_orders(proposal) if proposal.trades else []
                orders.extend(new)
                results.append({**_proposal_view(proposal, before, after), "client_name": pf.account.client_name,
                                "orders_created": len(new)})
            except Exception as exc:
                results.append({"account_id": account_id, "error": str(exc).strip("'\"")})
        if not ids:
            results.append({"error": "No matching accounts. Give account IDs or a client name."})
        return _dumps({"accounts": results, "orders_created": len(orders), "order_status": "Pending"}), orders

    @tool
    @safe
    def explain_methodology(topic: str) -> str:
        """Explain how the simulation works (sampling, copulas, distributions, success, limitations)."""
        return _dumps({"topic": topic, "text": find_section(topic)})

    @tool
    @safe
    def get_capital_market_assumptions() -> str:
        """Return expected returns, volatility, distributions, correlations and inflation."""
        d = cma.to_dict()
        return _dumps({"inflation": pct(d["inflation"]),
                       "expected_return": {k: pct(v) for k, v in d["expected_return"].items()},
                       "volatility": {k: pct(v) for k, v in d["volatility"].items()},
                       "distributions": d["distributions"], "asset_classes": d["asset_classes"],
                       "correlation": d["correlation"]})

    return [list_accounts, list_model_portfolios, get_account_portfolio, run_simulation,
            compare_current_vs_model, propose_rebalance_tool, simulate_and_rebalance,
            explain_methodology, get_capital_market_assumptions]
