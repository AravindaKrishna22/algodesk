from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class State(str, Enum):
    FLAT = "FLAT"
    SIGNAL = "SIGNAL"
    IN_POSITION = "IN_POSITION"
    PARTIAL_EXIT = "PARTIAL_EXIT"


class Action(str, Enum):
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body_top(self) -> float:
        return max(self.open, self.close)

    @property
    def body_bottom(self) -> float:
        return min(self.open, self.close)

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_green(self) -> bool:
        return self.close > self.open

    @property
    def is_red(self) -> bool:
        return self.close < self.open

    def close_time(self, timeframe_minutes: int) -> datetime:
        return self.ts + timedelta(minutes=timeframe_minutes)


@dataclass
class Intent:
    action: Action
    stop: Optional[float] = None
    target_rs: List[Tuple[float, float]] = field(default_factory=list)
    trail_r: Optional[float] = None
    breakeven_after_first_target: bool = True
    reason: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    side: str
    instrument: str
    entry_ts: str
    entry_price: float
    initial_qty: int
    qty: int
    stop: Optional[float]
    stop_kind: str = "INITIAL"
    initial_stop: Optional[float] = None
    risk: Optional[float] = None
    targets: List[Dict[str, Any]] = field(default_factory=list)
    trail_r: Optional[float] = None
    breakeven_after_first_target: bool = True
    best_price: float = 0.0
    targets_hit: int = 0
    legs: List[Dict[str, Any]] = field(default_factory=list)
    entry_costs: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_long(self) -> bool:
        return self.side == Side.LONG.value

    @property
    def sign(self) -> int:
        return 1 if self.is_long else -1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Position":
        return cls(**d)