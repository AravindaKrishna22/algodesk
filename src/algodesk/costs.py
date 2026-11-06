from __future__ import annotations

from typing import Any, Dict


class CostModel:
    def __init__(self, costs: Dict[str, Any], slippage_points: float = 0.0):
        self.brokerage_flat = float(costs.get("brokerage_flat", 0.0) or 0.0)
        self.brokerage_pct = float(costs.get("brokerage_pct", 0.0) or 0.0)
        self.stt_sell_pct = float(costs.get("stt_sell_pct", 0.0) or 0.0)
        self.exchange_txn_pct = float(costs.get("exchange_txn_pct", 0.0) or 0.0)
        self.sebi_per_crore = float(costs.get("sebi_per_crore", 0.0) or 0.0)
        self.gst_pct = float(costs.get("gst_pct", 0.0) or 0.0)
        self.stamp_buy_pct = float(costs.get("stamp_buy_pct", 0.0) or 0.0)
        self.slippage_points = float(slippage_points)

    def fill_price(self, side: str, price: float) -> float:
        if side == "BUY":
            return price + self.slippage_points
        if side == "SELL":
            return price - self.slippage_points
        raise ValueError("side must be BUY or SELL")

    def breakdown(self, side: str, price: float, qty: int) -> Dict[str, float]:
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        turnover = price * qty
        candidates = []
        if self.brokerage_flat > 0:
            candidates.append(self.brokerage_flat)
        if self.brokerage_pct > 0:
            candidates.append(self.brokerage_pct / 100.0 * turnover)
        brokerage = min(candidates) if candidates else 0.0
        stt = self.stt_sell_pct / 100.0 * turnover if side == "SELL" else 0.0
        exchange = self.exchange_txn_pct / 100.0 * turnover
        sebi = self.sebi_per_crore * turnover / 1e7
        gst = self.gst_pct / 100.0 * (brokerage + exchange + sebi)
        stamp = self.stamp_buy_pct / 100.0 * turnover if side == "BUY" else 0.0
        total = brokerage + stt + exchange + sebi + gst + stamp
        return {
            "brokerage": brokerage,
            "stt": stt,
            "exchange": exchange,
            "sebi": sebi,
            "gst": gst,
            "stamp": stamp,
            "total": total,
        }

    def total(self, side: str, price: float, qty: int) -> float:
        return self.breakdown(side, price, qty)["total"]