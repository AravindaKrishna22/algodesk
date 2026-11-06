from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from ..indicators import EMA, VWMA
from ..models import Action, Candle, Intent, Position
from .base import Strategy, parse_hhmm, within_window


class StrategyB(Strategy):
    name = "B"

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        lengths = sorted(set(int(n) for n in cfg["short_emas"]) | set(int(n) for n in cfg["long_emas"]))
        self.emas = {n: EMA(n) for n in lengths}
        self.vwma = VWMA(int(cfg["vwma_length"]))
        self.anchor_key = f"ema{int(cfg['anchor_ema'])}"
        self.fast_keys = [str(k) for k in cfg["fast_lines"]]
        valid = {f"ema{n}" for n in lengths} | {"vwma"}
        for key in [self.anchor_key] + self.fast_keys:
            if key not in valid:
                raise ValueError(f"unknown line '{key}'. Valid lines: {sorted(valid)}")
        self.earliest = parse_hhmm(cfg["earliest_entry"])
        self.latest = parse_hhmm(cfg["latest_entry"])
        self.protective_stop_pct = cfg.get("protective_stop_pct")
        self.values: Dict[str, Optional[float]] = {}
        self.regime: Optional[str] = None
        self.prev_regime: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.regime is not None

    def feed(self, candle: Candle) -> None:
        vals: Dict[str, Optional[float]] = {}
        for n, ema in self.emas.items():
            vals[f"ema{n}"] = ema.update(candle.close)
        vals["vwma"] = self.vwma.update(candle.close, candle.volume)
        self.values = vals
        new_regime = self._compute_regime(vals)
        if new_regime is not None and new_regime != self.regime:
            self.prev_regime = self.regime
        self.regime = new_regime

    def _compute_regime(self, vals: Dict[str, Optional[float]]) -> Optional[str]:
        if any(v is None for v in vals.values()):
            return None
        anchor = vals[self.anchor_key]
        fast = [vals[k] for k in self.fast_keys]
        if all(f > anchor for f in fast):
            return "BULL"
        if all(f < anchor for f in fast):
            return "BEAR"
        return "NEUTRAL"

    def decide(
        self, candle: Candle, close_ts: datetime, position: Optional[Position]
    ) -> Optional[Intent]:
        if not self.ready:
            return None
        anchor = self.values[self.anchor_key]
        fast = [self.values[k] for k in self.fast_keys]
        if position is not None:
            if position.is_long and all(f < anchor for f in fast):
                return Intent(Action.EXIT, reason="B_CROSSOVER_EXIT")
            if (not position.is_long) and all(f > anchor for f in fast):
                return Intent(Action.EXIT, reason="B_CROSSOVER_EXIT")
            return None
        if not within_window(close_ts.time(), self.earliest, self.latest):
            return None
        # Removed "if self.prev_regime is None: return None" — was blocking the first trade
        if self.regime == "BULL" and self.prev_regime != "BULL":
            return self._entry(Action.ENTER_LONG, candle, anchor)
        if self.regime == "BEAR" and self.prev_regime != "BEAR":
            return self._entry(Action.ENTER_SHORT, candle, anchor)
        return None

    def _entry(self, action: Action, c: Candle, anchor: float) -> Intent:
        stop = None
        if self.protective_stop_pct:
            pct = float(self.protective_stop_pct) / 100.0
            stop = c.close * (1 - pct) if action == Action.ENTER_LONG else c.close * (1 + pct)
        side = "LONG" if action == Action.ENTER_LONG else "SHORT"
        return Intent(
            action=action,
            stop=stop,
            target_rs=[],
            trail_r=None,
            breakeven_after_first_target=False,
            reason=f"B_{side}_CROSSOVER",
            meta={"anchor": anchor, "fast": {k: self.values[k] for k in self.fast_keys}},
        )

    def on_entry(self, close_ts: datetime) -> None:
        self.prev_regime = self.regime

    def on_trade_closed(self, exit_close_ts: datetime) -> None:
        self.prev_regime = self.regime

    def get_state(self) -> Dict[str, Any]:
        return {"prev_regime": self.prev_regime, "regime": self.regime}

    def set_state(self, state: Dict[str, Any]) -> None:
        self.prev_regime = state.get("prev_regime")
        self.regime = state.get("regime")