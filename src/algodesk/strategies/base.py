from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, time
from typing import Any, Dict, Optional

from ..models import Candle, Intent, Position


def parse_hhmm(value: str) -> time:
    hours, minutes = str(value).split(":")
    return time(int(hours), int(minutes))


def within_window(t: time, start: time, end: time) -> bool:
    return start <= t <= end


class Strategy(ABC):
    name = "base"

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.timeframe_minutes = int(cfg["timeframe_minutes"])

    @property
    def ready(self) -> bool:
        return True

    @abstractmethod
    def feed(self, candle: Candle) -> None:
        ...

    @abstractmethod
    def decide(
        self, candle: Candle, close_ts: datetime, position: Optional[Position]
    ) -> Optional[Intent]:
        ...

    def has_pending(self) -> bool:
        return False

    def on_entry(self, close_ts: datetime) -> None:
        return None

    def on_trade_closed(self, exit_close_ts: datetime) -> None:
        return None

    def get_state(self) -> Dict[str, Any]:
        return {}

    def set_state(self, state: Dict[str, Any]) -> None:
        return None