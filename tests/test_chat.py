from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app import deps
from app.agent import AdvisorAgent
from app.deps import AgentCache


class FakeToolModel(BaseChatModel):
    """Replays scripted AI messages so tests do not need an LLM."""

    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool-model"

    def bind_tools(self, tools, **kwargs: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _cache(script):
    def factory(provider, model):
        return AdvisorAgent(FakeToolModel(script=script), deps.get_sources(), deps.get_cma(),
                            deps.get_rebalance_settings(), max_trials=1000)
    return AgentCache(factory)


def _call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def test_chat_runs_tools_and_adds_orders(client):
    script = [
        _call("simulate_and_rebalance", {"client_name": "Jane"}),
        AIMessage(content="Created pending orders for Jane Smith. Projections are not guarantees."),
    ]
    cache = _cache(script)
    client.app.dependency_overrides[deps.get_agent_cache] = lambda: cache
    r = client.post("/api/chat", json={"message": "Simulate and rebalance Jane", "thread_id": "t1",
                                       "provider": "ollama", "account_id": "A1001"})
    body = r.json()
    assert r.status_code == 200
    assert body["text"].startswith("Created pending orders")
    assert body["tool_calls"][0]["tool"] == "simulate_and_rebalance"
    assert body["orders_added"] > 0 and body["orders_added"] == len(body["orders"])
    assert len(client.get("/api/orders").json()) == body["orders_added"]


def test_chat_tool_error_is_returned_as_json(client):
    script = [_call("get_account_portfolio", {"account_id": "ZZZ"}), AIMessage(content="Unknown account.")]
    cache = _cache(script)
    client.app.dependency_overrides[deps.get_agent_cache] = lambda: cache
    body = client.post("/api/chat", json={"message": "x", "thread_id": "t2", "provider": "ollama"}).json()
    assert '"error"' in body["tool_calls"][0]["result"] and body["orders_added"] == 0


def test_chat_selection_prefix_and_reset(client):
    cache = _cache([AIMessage(content="Hello")])
    client.app.dependency_overrides[deps.get_agent_cache] = lambda: cache
    client.post("/api/chat", json={"message": "hi", "thread_id": "t3", "provider": "ollama",
                                   "account_id": "A1001", "model_id": "MOD-60-40"})
    agent = cache.get("ollama", None)
    state = agent.graph.get_state({"configurable": {"thread_id": "t3"}})
    first = state.values["messages"][0].content
    assert first.startswith("[Account selected in the app: A1001") and "MOD-60-40" in first
    assert client.delete("/api/chat/t3").json() == {"reset": True}
    assert not agent.graph.get_state({"configurable": {"thread_id": "t3"}}).values


def test_chat_provider_failure_returns_502(client):
    class Broken:
        def ask(self, *a, **k):
            raise RuntimeError("boom")

    class Cache:
        def get(self, provider, model):
            return Broken()

    client.app.dependency_overrides[deps.get_agent_cache] = lambda: Cache()
    r = client.post("/api/chat", json={"message": "x", "thread_id": "t4", "provider": "ollama"})
    assert r.status_code == 502
