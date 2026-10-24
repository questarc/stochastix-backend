from . import chat, llm, methodology, orders, portfolio, rebalance, simulations, sources

ALL_ROUTERS = [
    sources.router,
    portfolio.router,
    simulations.router,
    rebalance.router,
    orders.router,
    methodology.router,
    llm.router,
    chat.router,
]
