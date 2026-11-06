from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

# Try to import kiteconnect (for live Zerodha API)
try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False


class BrokerError(Exception):
    pass


@dataclass
class OrderRequest:
    client_order_id: str
    instrument: str
    side: str
    qty: int
    price: float
    kind: str
    ts: str


@dataclass
class OrderResponse:
    client_order_id: str
    status: str
    fill_price: float = 0.0
    fill_qty: int = 0
    message: str = ""
    broker_order_id: str = ""
    duplicate: bool = False


class BrokerBase(ABC):
    name = "base"

    @abstractmethod
    def place_order(self, req: OrderRequest) -> OrderResponse:
        ...

    @abstractmethod
    def get_positions(self) -> Dict[str, int]:
        ...

    def snapshot(self) -> Dict[str, Any]:
        return {}

    def restore(self, data: Dict[str, Any]) -> None:
        return None


class PaperBroker(BrokerBase):
    name = "paper"

    def __init__(self):
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.positions: Dict[str, int] = {}
        self._counter = 0
        self._reject_queue = []
        self._error_queue = []

    def reject_next(self, n: int = 1, message: str = "rejected") -> None:
        self._reject_queue.extend([message] * n)

    def fail_next(self, n: int = 1, message: str = "broker unavailable") -> None:
        self._error_queue.extend([message] * n)

    def place_order(self, req: OrderRequest) -> OrderResponse:
        if req.side not in ("BUY", "SELL"):
            return OrderResponse(req.client_order_id, "REJECTED", message="invalid side")
        if req.qty <= 0:
            return OrderResponse(req.client_order_id, "REJECTED", message="invalid quantity")
        existing = self.orders.get(req.client_order_id)
        if existing is not None and existing["status"] == "FILLED":
            resp = OrderResponse(**existing)
            resp.duplicate = True
            return resp
        if self._error_queue:
            raise BrokerError(self._error_queue.pop(0))
        if self._reject_queue:
            return OrderResponse(
                req.client_order_id, "REJECTED", message=self._reject_queue.pop(0)
            )
        self._counter += 1
        resp = OrderResponse(
            client_order_id=req.client_order_id,
            status="FILLED",
            fill_price=req.price,
            fill_qty=req.qty,
            message="filled",
            broker_order_id=f"PAPER-{self._counter:08d}",
        )
        delta = req.qty if req.side == "BUY" else -req.qty
        net = self.positions.get(req.instrument, 0) + delta
        if net == 0:
            self.positions.pop(req.instrument, None)
        else:
            self.positions[req.instrument] = net
        self.orders[req.client_order_id] = asdict(resp)
        return resp

    def get_positions(self) -> Dict[str, int]:
        return dict(self.positions)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "orders": dict(self.orders),
            "positions": dict(self.positions),
            "counter": self._counter,
        }

    def restore(self, data: Dict[str, Any]) -> None:
        self.orders = dict(data.get("orders", {}))
        self.positions = {k: int(v) for k, v in data.get("positions", {}).items()}
        self._counter = int(data.get("counter", 0))


class ZerodhaBroker(BrokerBase):
    """
    Live broker adapter for Zerodha Kite Connect.
    Demonstrates the adapter pattern: one class, zero changes to strategy code.
    """
    name = "zerodha"

    def __init__(self):
        if not KITE_AVAILABLE:
            raise ImportError("pip install kiteconnect to use ZerodhaBroker")
        
        creds = load_credentials(prefix="ZERODHA")
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN must be set in .env")
            
        self.kite = KiteConnect(api_key=creds["api_key"])
        self.kite.set_access_token(creds["access_token"])
        self._positions = {}

    def place_order(self, req: OrderRequest) -> OrderResponse:
        try:
            txn_type = self.kite.TRANSACTION_TYPE_BUY if req.side == "BUY" else self.kite.TRANSACTION_TYPE_SELL
            
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=req.instrument,
                transaction_type=txn_type,
                quantity=req.qty,
                product=self.kite.PRODUCT_MIS, # Intraday
                order_type=self.kite.ORDER_TYPE_LIMIT if req.kind == "LIMIT" else self.kite.ORDER_TYPE_MARKET,
                price=req.price if req.kind == "LIMIT" else None,
                tag=req.client_order_id[:20] # Zerodha limit
            )
            
            return OrderResponse(
                client_order_id=req.client_order_id,
                status="FILLED",
                fill_price=req.price,
                fill_qty=req.qty,
                broker_order_id=str(order_id),
                message="Zerodha order placed"
            )
        except Exception as e:
            raise BrokerError(f"Zerodha rejected order: {str(e)}")

    def get_positions(self) -> Dict[str, int]:
        try:
            positions_data = self.kite.positions()["net"]
            pos = {}
            for p in positions_data:
                if p["quantity"] != 0:
                    pos[p["tradingsymbol"]] = p["quantity"]
            self._positions = pos
            return pos
        except Exception as e:
            raise BrokerError(f"Failed to fetch Zerodha positions: {str(e)}")

    def snapshot(self) -> Dict[str, Any]:
        return {"positions": self._positions}

    def restore(self, data: Dict[str, Any]) -> None:
        self._positions = data.get("positions", {})


def load_credentials(prefix: str = "BROKER") -> Dict[str, Optional[str]]:
    return {
        "api_key": os.environ.get(f"{prefix}_API_KEY"),
        "api_secret": os.environ.get(f"{prefix}_API_SECRET"),
        "access_token": os.environ.get(f"{prefix}_ACCESS_TOKEN"),
    }


# Registry of available brokers
BROKERS = {
    "paper": PaperBroker,
    "zerodha": ZerodhaBroker
}


def create_broker(name: str = "paper", **kwargs) -> BrokerBase:
    key = (name or "paper").lower()
    if key not in BROKERS:
        raise ValueError(f"unknown broker '{name}'. Registered: {sorted(BROKERS)}")
    return BROKERS[key](**kwargs)