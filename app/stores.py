"""In-memory stores behind small interfaces so a database can replace them later."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from .domain import Position
from .rebalance import merge_orders


class OrderStore(ABC):
    @abstractmethod
    def list(self) -> list[dict]: ...

    @abstractmethod
    def merge(self, orders: list[dict]) -> list[dict]: ...

    @abstractmethod
    def clear(self) -> None: ...


class InMemoryOrderStore(OrderStore):
    def __init__(self) -> None:
        self._orders: list[dict] = []
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(o) for o in self._orders]

    def merge(self, orders: list[dict]) -> list[dict]:
        with self._lock:
            self._orders = merge_orders(self._orders, orders)
            return list(orders)

    def clear(self) -> None:
        with self._lock:
            self._orders = []


class UploadStore(ABC):
    @abstractmethod
    def get(self, source: str, account_id: str) -> list[Position] | None: ...

    @abstractmethod
    def set(self, source: str, account_id: str, positions: list[Position]) -> None: ...

    @abstractmethod
    def reset(self, source: str, account_id: str) -> bool: ...


class InMemoryUploadStore(UploadStore):
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], list[Position]] = {}
        self._lock = threading.Lock()

    def get(self, source: str, account_id: str) -> list[Position] | None:
        with self._lock:
            return self._data.get((source, account_id))

    def set(self, source: str, account_id: str, positions: list[Position]) -> None:
        with self._lock:
            self._data[(source, account_id)] = list(positions)

    def reset(self, source: str, account_id: str) -> bool:
        with self._lock:
            return self._data.pop((source, account_id), None) is not None
