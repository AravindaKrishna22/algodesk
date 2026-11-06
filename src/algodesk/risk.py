from __future__ import annotations

import os
from typing import Any, Dict, Tuple


class RiskManager:
    def __init__(self, cfg: Dict[str, Any]):
        self.max_daily_loss = float(cfg.get("max_daily_loss", 0) or 0)
        self.max_trades_per_day = int(cfg.get("max_trades_per_day", 0) or 0)
        self.max_open_positions = int(cfg.get("max_open_positions", 1) or 1)
        self.kill_switch_file = os.environ.get("KILL_SWITCH_FILE") or cfg.get("kill_switch_file")
        self._kill = False

    def request_kill(self) -> None:
        self._kill = True

    def kill_requested(self) -> bool:
        if self._kill:
            return True
        if self.kill_switch_file and os.path.exists(self.kill_switch_file):
            return True
        return False

    def daily_loss_breached(self, day_pnl: float) -> bool:
        return self.max_daily_loss > 0 and day_pnl <= -self.max_daily_loss

    def allow_entry(
        self, trades_today: int, open_positions: int, day_pnl: float
    ) -> Tuple[bool, str]:
        if self.kill_requested():
            return False, "kill_switch"
        if self.daily_loss_breached(day_pnl):
            return False, "max_daily_loss"
        if self.max_trades_per_day > 0 and trades_today >= self.max_trades_per_day:
            return False, "max_trades_per_day"
        if open_positions >= self.max_open_positions:
            return False, "max_open_positions"
        return True, ""