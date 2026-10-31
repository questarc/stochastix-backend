"""Positions source agent: accounts and models from CSV, positions from A360 Positions exports."""
from __future__ import annotations

import io
import math
from pathlib import Path

import pandas as pd

from ..domain import Position
from .base import register
from .sales_agent import SalesAgent

REQUIRED_COLUMNS = ("Qty", "Market Value", "Ticker", "Cusip")


def parse_number(value) -> float:
    """Parse '$1,234.50', '+12', '(123)' (= -123) and blanks (= 0)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return 0.0 if (isinstance(value, float) and math.isnan(value)) else float(value)
    text = str(value).strip().replace("$", "").replace(",", "").replace("+", "")
    if not text:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    number = float(text) if text else 0.0
    return -number if negative else number


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def classify_asset(ticker: str, sec_type: str, config: dict) -> str:
    ticker_map = {k.upper(): v for k, v in config.get("ticker_asset_class", {}).items()}
    if ticker.upper() in ticker_map:
        return ticker_map[ticker.upper()]
    sec_map = {k.lower(): v for k, v in config.get("sec_type_asset_class", {}).items()}
    if sec_type.lower() in sec_map:
        return sec_map[sec_type.lower()]
    return config.get("default_asset_class", "US Equity")


def parse_positions(source, account_id: str, config: dict) -> list[Position]:
    """Parse an A360 Positions export (path, bytes or text) into positions for ``account_id``."""
    if isinstance(source, (bytes, bytearray)):
        source = io.StringIO(source.decode("utf-8-sig"))
    elif isinstance(source, str) and not Path(source).exists():
        source = io.StringIO(source)
    df = pd.read_csv(source, dtype=str, keep_default_na=False, skip_blank_lines=True)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Not an A360 Positions file; missing columns: {missing}")

    positions: list[Position] = []
    for row in df.to_dict(orient="records"):
        qty = parse_number(row.get("Qty"))
        if qty == 0 and _text(row.get("Qty")) == "":
            qty = parse_number(row.get("Custodian Quantity"))
        ticker = _text(row.get("Ticker")) or _text(row.get("Cusip"))
        if qty <= 0 or not ticker:
            continue
        market_value = parse_number(row.get("Market Value"))
        price = parse_number(row.get("PM Price"))
        if price == 0:
            price = market_value / qty
        asset_class = classify_asset(ticker, _text(row.get("Sec Type")), config)
        positions.append(Position(account_id, ticker, asset_class, qty, price))
    return positions


@register("positions")
class A360PositionsAgent(SalesAgent):
    supports_upload = True

    def __init__(self, config: dict, base_dir):
        super().__init__(config, base_dir)
        self.upload_store = None

    def get_positions(self, account_id: str) -> list[Position]:
        self.get_account(account_id)
        if self.upload_store is not None:
            uploaded = self.upload_store.get(self.name, account_id)
            if uploaded is not None:
                return uploaded
        files = self.config.get("positions_files", {})
        if account_id not in files:
            return []
        return parse_positions(str(self.resolve_path(files[account_id])), account_id, self.config)

    def parse_upload(self, content: bytes, account_id: str) -> list[Position]:
        self.get_account(account_id)
        return parse_positions(content, account_id, self.config)
