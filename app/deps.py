"""Cached application singletons, injected into routers with FastAPI ``Depends``."""
from __future__ import annotations

import threading
from functools import lru_cache
from typing import Callable

from .agent import AdvisorAgent, build_tools
from .engine import CapitalMarketAssumptions
from .llm import LLMSettings, build_chat_model
from .rebalance import RebalanceSettings
from .sources import SourceAgent, load_sources
from .sources.base import BASE_DIR
from .stores import InMemoryOrderStore, InMemoryUploadStore, OrderStore, UploadStore

CONFIG_DIR = BASE_DIR / "config"


@lru_cache
def get_upload_store() -> UploadStore:
    return InMemoryUploadStore()


@lru_cache
def get_order_store() -> OrderStore:
    return InMemoryOrderStore()


@lru_cache
def get_sources() -> dict[str, SourceAgent]:
    sources = load_sources(CONFIG_DIR / "sources.json")
    for source in sources.values():
        if hasattr(source, "upload_store"):
            source.upload_store = get_upload_store()
    return sources


@lru_cache
def get_cma() -> CapitalMarketAssumptions:
    return CapitalMarketAssumptions.load(CONFIG_DIR / "capital_market_assumptions.json")


@lru_cache
def get_rebalance_settings() -> RebalanceSettings:
    return RebalanceSettings.load(CONFIG_DIR / "rebalance.json")


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings.load(CONFIG_DIR / "llm.json")


class AgentCache:
    """One Advisor AI agent per (provider, model)."""

    def __init__(self, factory: Callable[[str, str | None], AdvisorAgent]):
        self._factory = factory
        self._agents: dict[tuple[str, str | None], AdvisorAgent] = {}
        self._lock = threading.Lock()

    def get(self, provider: str, model: str | None) -> AdvisorAgent:
        key = (provider, model)
        with self._lock:
            if key not in self._agents:
                self._agents[key] = self._factory(provider, model)
            return self._agents[key]

    def reset_thread(self, thread_id: str) -> None:
        with self._lock:
            agents = list(self._agents.values())
        for agent in agents:
            agent.reset(thread_id)


def _build_agent(provider: str, model: str | None) -> AdvisorAgent:
    settings = get_llm_settings()
    llm = build_chat_model(settings, provider, model)
    return AdvisorAgent(llm, get_sources(), get_cma(), get_rebalance_settings(),
                        max_trials=settings.max_trials_per_tool_call)


@lru_cache
def get_agent_cache() -> AgentCache:
    return AgentCache(_build_agent)


@lru_cache
def get_agent_tools() -> dict:
    """Advisor AI tools by name, for agents that run in the browser (WebLLM)."""
    tools = build_tools(get_sources(), get_cma(), get_rebalance_settings(),
                        get_llm_settings().max_trials_per_tool_call)
    return {t.name: t for t in tools}
