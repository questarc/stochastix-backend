from . import agent_tools, chat, llm, methodology, orders, portfolio, rebalance, simulations, sources, video, voice

ALL_ROUTERS = [
    sources.router,
    portfolio.router,
    simulations.router,
    rebalance.router,
    orders.router,
    methodology.router,
    llm.router,
    chat.router,
    agent_tools.router,
    voice.router,
    video.router,
]
