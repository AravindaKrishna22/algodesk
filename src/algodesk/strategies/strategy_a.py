from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, Optional

from ..indicators import MACD, SMA
from ..models import Action, Candle, Intent, Position
from .base import Strategy, parse_hhmm, within_window


class StrategyA(Strategy):
    name = "A"

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.sma_hi = SMA(int(cfg["sma_length"]))
        self.sma_lo = SMA(int(cfg["sma_length"]))
        m = cfg["macd"]
        self.macd = MACD(int(m["fast"]), int(m["slow"]), int(m["signal"]))
        self.lookback = int(cfg["macd_cross_lookback"])
        self.min_fraction = float(cfg["min_body_fraction_beyond_band"])
        self.window = int(cfg["breakout_window_candles"])
        self.body_n = int(cfg["body_avg_lookback"])
        self.max_multiple = float(cfg["max_body_multiple"])
        self.earliest = parse_hhmm(cfg["earliest_entry"])
        self.latest = parse_hhmm(cfg["latest_entry"])
        self.cooldown = timedelta(minutes=float(cfg["cooldown_minutes"]))
        self.targets = [(float(r), float(f)) for r, f in cfg["targets"]]
        self.trail_r = cfg.get("trail_r")
        self.breakeven = bool(cfg.get("breakeven_after_first_target", True))
        self._bodies: Deque[float] = deque(maxlen=self.body_n)
        self._prev_diff: Optional[float] = None
        self._since_up: Optional[int] = None
        self._since_dn: Optional[int] = None
        self.snap: Dict[str, Any] = {"sma_hi": None, "sma_lo": None, "macd": None, "avg_body": None}
        self.pending: Optional[Dict[str, Any]] = None
        self.cooldown_until: Optional[datetime] = None

    @property
    def ready(self) -> bool:
        s = self.snap
        return (
            s["sma_hi"] is not None
            and s["sma_lo"] is not None
            and s["macd"] is not None
            and s["avg_body"] is not None
        )

    def feed(self, candle: Candle) -> None:
        hi = self.sma_hi.update(candle.high)
        lo = self.sma_lo.update(candle.low)
        macd = self.macd.update(candle.close)
        avg_prev = sum(self._bodies) / self.body_n if len(self._bodies) == self.body_n else None
        self._bodies.append(candle.body)
        if self._since_up is not None:
            self._since_up += 1
        if self._since_dn is not None:
            self._since_dn += 1
        if macd is not None:
            diff = macd[0] - macd[1]
            if self._prev_diff is not None:
                if self._prev_diff <= 0 < diff:
                    self._since_up = 0
                if self._prev_diff >= 0 > diff:
                    self._since_dn = 0
            self._prev_diff = diff
        self.snap = {"sma_hi": hi, "sma_lo": lo, "macd": macd, "avg_body": avg_prev}

    def has_pending(self) -> bool:
        return self.pending is not None

    def _cooling(self, close_ts: datetime) -> bool:
        return self.cooldown_until is not None and close_ts < self.cooldown_until

    def _macd_recent(self, since: Optional[int]) -> bool:
        return since is not None and since <= self.lookback - 1

    def decide(
        self, candle: Candle, close_ts: datetime, position: Optional[Position]
    ) -> Optional[Intent]:
        if position is not None:
            self.pending = None
            return None
        if not self.ready:
            return None
        if self.pending is not None:
            intent = self._check_breakout(candle, close_ts)
            if intent is not None:
                return intent
        if self.pending is None:
            self._detect_signal(candle, close_ts)
        return None

    def _detect_signal(self, c: Candle, close_ts: datetime) -> None:
        if not within_window(close_ts.time(), self.earliest, self.latest):
            return
        if self._cooling(close_ts):
            return
        body = c.body
        if body <= 0:
            return
        s = self.snap
        if body > self.max_multiple * s["avg_body"]:
            return
        diff = self._prev_diff
        if diff is None:
            return
        if c.is_green and diff > 0 and self._macd_recent(self._since_up):
            above = max(0.0, c.body_top - max(c.body_bottom, s["sma_hi"]))
            if above / body >= self.min_fraction:
                self.pending = {
                    "side": "LONG",
                    "ts": c.ts.isoformat(),
                    "sig_high": c.high,
                    "sig_low": c.low,
                    "stop": s["sma_lo"],
                    "waited": 0,
                }
                return
        if c.is_red and diff < 0 and self._macd_recent(self._since_dn):
            below = max(0.0, min(c.body_top, s["sma_lo"]) - c.body_bottom)
            if below / body >= self.min_fraction:
                self.pending = {
                    "side": "SHORT",
                    "ts": c.ts.isoformat(),
                    "sig_high": c.high,
                    "sig_low": c.low,
                    "stop": s["sma_hi"],
                    "waited": 0,
                }

    def _check_breakout(self, c: Candle, close_ts: datetime) -> Optional[Intent]:
        p = self.pending
        if p["ts"] == c.ts.isoformat():
            return None
        p["waited"] += 1
        if self._cooling(close_ts) or close_ts.time() > self.latest:
            self.pending = None
            return None
        
        if p["side"] == "LONG" and c.close > p["sig_high"]:
            self.pending = None
            risk_points = c.close - p["stop"]
            # FIX: Ensure minimum risk (0.5 points) to avoid micro-trades
            if risk_points < 0.5 or p["stop"] >= c.close:
                return None
            return self._intent(Action.ENTER_LONG, p)
            
        if p["side"] == "SHORT" and c.close < p["sig_low"]:
            self.pending = None
            risk_points = p["stop"] - c.close
            # FIX: Ensure minimum risk (0.5 points) to avoid micro-trades
            if risk_points < 0.5 or p["stop"] <= c.close:
                return None
            return self._intent(Action.ENTER_SHORT, p)
            
        if p["waited"] >= self.window:
            self.pending = None
        return None

    def _intent(self, action: Action, p: Dict[str, Any]) -> Intent:
        return Intent(
            action=action,
            stop=p["stop"],
            target_rs=list(self.targets),
            trail_r=self.trail_r,
            breakeven_after_first_target=self.breakeven,
            reason=f"A_{p['side']}_BREAKOUT",
            meta={"signal_ts": p["ts"], "sig_high": p["sig_high"], "sig_low": p["sig_low"]},
        )

    def on_entry(self, close_ts: datetime) -> None:
        self.pending = None

    def on_trade_closed(self, exit_close_ts: datetime) -> None:
        self.cooldown_until = exit_close_ts + self.cooldown

    def get_state(self) -> Dict[str, Any]:
        return {
            "pending": self.pending,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
        }

    def set_state(self, state: Dict[str, Any]) -> None:
        self.pending = state.get("pending")
        cu = state.get("cooldown_until")
        self.cooldown_until = datetime.fromisoformat(cu) if cu else None