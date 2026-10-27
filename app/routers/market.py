from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from ..deps import get_corporate_actions_agent, get_earnings_agent, get_market_agent
from ..market import CorporateActionsAgent, EarningsAgent, MarketAnalyzerAgent

router = APIRouter(tags=["market"])

NOTICE = "Third-party information shown as published; not verified and not investment advice."


@router.get("/market/news")
async def market_news(refresh: bool = False, topic: str | None = None,
                      agent: MarketAnalyzerAgent = Depends(get_market_agent)):
    result = await run_in_threadpool(agent.news, refresh, topic)
    return {"agent": "MarketAnalyzerAgent", "notice": NOTICE, **result}


@router.get("/market/earnings")
async def market_earnings(days: int = Query(14, ge=1, le=30), refresh: bool = False,
                          agent: EarningsAgent = Depends(get_earnings_agent)):
    result = await run_in_threadpool(agent.upcoming, days, refresh)
    return {"agent": "EarningsAgent", "notice": NOTICE, **result}


@router.get("/market/corporate-actions")
async def corporate_actions(days: int = Query(30, ge=1, le=60), refresh: bool = False,
                            agent: CorporateActionsAgent = Depends(get_corporate_actions_agent)):
    result = await run_in_threadpool(agent.upcoming, days, refresh)
    return {"agent": "CorporateActionsAgent", "notice": NOTICE, **result}
