from __future__ import annotations

import math
import time as _time
from datetime import datetime, time
from typing import Any, Dict, Iterable, List, Optional

from .broker import BrokerBase, BrokerError, OrderRequest, OrderResponse
from .costs import CostModel
from .logging_setup import EventLogger, get_event_logger
from .models import Action, Candle, Intent, Position, State
from .risk import RiskManager
from .state_machine import TradeStateMachine
from .state_store import JSONStateStore
from .strategies.base import Strategy, parse_hhmm

SNAPSHOT_VERSION = 1

STOP_REASONS = {"INITIAL": "STOP_LOSS", "BREAKEVEN": "BREAKEVEN_STOP", "TRAIL": "TRAIL_STOP"}

class Engine:
    def __init__(
        self,
        strategy: Strategy,
        broker: BrokerBase,
        costs: CostModel,
        risk: RiskManager,
        settings: Dict[str, Any],
        instrument: Dict[str, Any],
        store: Optional[JSONStateStore] = None,
        logger: Optional[EventLogger] = None,
    ):
        self.strategy = strategy
        self.broker = broker
        self.costs = costs
        self.risk = risk
        self.store = store
        self.log = logger or get_event_logger()

        self.symbol = str(settings["symbol"])
        self.capital = float(settings.get("capital", 0.0))
        self.tf = strategy.timeframe_minutes
        self.lots = int(settings["sizing"]["lots"])
        sess = settings["session"]
        self.session_open = parse_hhmm(sess["open"])
        self.session_close = parse_hhmm(sess.get("close", "15:30"))
        self.squareoff = parse_hhmm(sess["squareoff"])
        ex = settings.get("execution", {})
        self.same_candle_rule = str(ex.get("same_candle_rule", "stop_first"))
        if self.same_candle_rule not in ("stop_first", "target_first"):
            raise ValueError("execution.same_candle_rule must be stop_first or target_first")
        self.attempts = 1 + int(ex.get("order_retries", 0))
        self.retry_backoff = float(ex.get("retry_backoff_seconds", 0.0))
        self.min_entry_price = float(ex.get("min_entry_price", 0.0))
        self.breakeven_offset = float(ex.get("breakeven_offset_points", 0.0))

        self.lot_size = int(instrument["lot_size"])
        if self.lot_size <= 0:
            raise ValueError("lot_size must come from instruments.yaml / instrument master and be > 0")
        fq = instrument.get("freeze_qty")
        self.freeze_qty = int(fq) if fq else None
        self.tick = float(instrument.get("tick_size", 0.0) or 0.0)

        self.sm = TradeStateMachine()
        self.position: Optional[Position] = None
        self.trades: List[Dict[str, Any]] = []
        self.equity: List[Dict[str, Any]] = []
        self.realized = 0.0
        self.day = None
        self.day_pnl = 0.0
        self.trades_today = 0
        self.last_close_ts: Optional[datetime] = None
        self._fed_upto: Optional[datetime] = None
        self.halted = False
        self.pending_exit: Optional[str] = None

    def run(self, candles: Iterable[Candle]) -> None:
        for c in candles:
            self.on_candle(c)

    def on_candle(self, candle: Candle) -> None:
        close_ts = candle.close_time(self.tf)

        if self._fed_upto is not None and close_ts <= self._fed_upto:
            self.log.event("duplicate_candle_ignored", ts=candle.ts.isoformat())
            return
        if candle.ts.time() < self.session_open or close_ts.time() > self.session_close:
            self.log.event("candle_outside_session", ts=candle.ts.isoformat())
            return
        if self.last_close_ts is not None and close_ts <= self.last_close_ts:
            self.strategy.feed(candle)
            self._fed_upto = close_ts
            return

        self._roll_day(candle, close_ts)

        if self.position is not None:
            self._manage_position(candle, close_ts)
        if self.position is not None:
            self._time_and_risk_exits(candle, close_ts)

        self.strategy.feed(candle)
        self._fed_upto = close_ts

        intent = self.strategy.decide(candle, close_ts, self.position)
        if intent is not None and intent.action == Action.EXIT:
            if self.position is not None:
                self._close_all(candle.close, close_ts, intent.reason or "SIGNAL_EXIT", slip=True)
            intent = self.strategy.decide(candle, close_ts, self.position)
        if intent is not None and intent.action in (Action.ENTER_LONG, Action.ENTER_SHORT):
            self._enter(intent, candle, close_ts)

        self._sync_state_machine(close_ts)
        self._record_equity(candle, close_ts)
        self.last_close_ts = close_ts
        self._persist()

    def recover(self) -> bool:
        if self.store is None or not self.store.exists():
            return False
        data = self.store.load()
        if not data:
            return False
        if data.get("version") != SNAPSHOT_VERSION:
            raise RuntimeError(f"unsupported snapshot version {data.get('version')}")
        self.broker.restore(data.get("broker", {}))
        self.sm = TradeStateMachine.from_dict(data["sm"])
        self.position = Position.from_dict(data["position"]) if data.get("position") else None
        self.strategy.set_state(data.get("strategy", {}))
        self.trades = list(data.get("trades", []))
        self.realized = float(data.get("realized", 0.0))
        self.day_pnl = float(data.get("day_pnl", 0.0))
        self.trades_today = int(data.get("trades_today", 0))
        self.halted = bool(data.get("halted", False))
        self.pending_exit = data.get("pending_exit")
        d = data.get("day")
        self.day = datetime.fromisoformat(d).date() if d else None
        lc = data.get("last_close_ts")
        self.last_close_ts = datetime.fromisoformat(lc) if lc else None

        broker_net = int(self.broker.get_positions().get(self.symbol, 0))
        expected = (self.position.sign * self.position.qty) if self.position else 0
        if broker_net != expected:
            self.halted = True
            self.log.error(
                "reconcile_mismatch", symbol=self.symbol, engine_net=expected, broker_net=broker_net
            )
        self.log.event(
            "recovered",
            last_close_ts=lc,
            state=self.sm.state.value,
            open_position=self.position is not None,
            reconciled=not self.halted,
        )
        return True

    def force_squareoff(self, price: float, ts: datetime, reason: str = "KILL_SWITCH") -> None:
        if self.position is not None:
            self._close_all(price, ts, reason, slip=True)
            self._sync_state_machine(ts)
            self._persist()

    def _round_tick(self, p: float) -> float:
        if self.tick > 0:
            return round(round(p / self.tick) * self.tick, 6)
        return p

    def _roll_day(self, candle: Candle, close_ts: datetime) -> None:
        day = candle.ts.date()
        if self.day == day:
            return
        if self.position is not None:
            self.log.error("stale_position_new_day", day=str(day))
            self._close_all(candle.open, candle.ts, "STALE_POSITION", slip=True)
        self.day = day
        self.day_pnl = 0.0
        self.trades_today = 0

    def _unrealized(self, price: float) -> float:
        p = self.position
        if p is None:
            return 0.0
        return p.sign * (price - p.entry_price) * p.qty

    def _chunks(self, qty: int) -> List[int]:
        if not self.freeze_qty or qty <= self.freeze_qty:
            return [qty]
        max_chunk = (self.freeze_qty // self.lot_size) * self.lot_size or self.freeze_qty
        out, left = [], qty
        while left > 0:
            q = min(max_chunk, left)
            out.append(q)
            left -= q
        return out

    def _send(
        self, cid: str, side: str, qty: int, price: float, kind: str, ts: datetime
    ) -> Optional[OrderResponse]:
        chunks = self._chunks(qty)
        filled, notional, last = 0, 0.0, None
        for i, q in enumerate(chunks):
            ccid = cid if len(chunks) == 1 else f"{cid}-p{i + 1}"
            resp = self._send_one(ccid, side, q, price, kind, ts)
            if resp is None:
                break
            filled += resp.fill_qty
            notional += resp.fill_price * resp.fill_qty
            last = resp
        if filled == 0 or last is None:
            return None
        if filled < qty:
            self.log.error("partial_fill_after_failure", client_order_id=cid, wanted=qty, filled=filled)
        agg = OrderResponse(
            client_order_id=cid,
            status="FILLED",
            fill_price=notional / filled,
            fill_qty=filled,
            message=last.message,
            broker_order_id=last.broker_order_id,
            duplicate=last.duplicate,
        )
        return agg

    def _send_one(
        self, cid: str, side: str, qty: int, price: float, kind: str, ts: datetime
    ) -> Optional[OrderResponse]:
        req = OrderRequest(cid, self.symbol, side, qty, price, kind, ts.isoformat())
        for attempt in range(1, self.attempts + 1):
            self.log.event(
                "order_request", client_order_id=cid, side=side, qty=qty, price=price, kind=kind, attempt=attempt
            )
            try:
                resp = self.broker.place_order(req)
            except BrokerError as exc:
                self.log.error("broker_error", client_order_id=cid, message=str(exc), attempt=attempt)
                resp = None
            if resp is not None:
                self.log.event(
                    "broker_response",
                    client_order_id=cid,
                    status=resp.status,
                    fill_price=resp.fill_price,
                    fill_qty=resp.fill_qty,
                    message=resp.message,
                    duplicate=resp.duplicate,
                )
                if resp.status == "FILLED" and resp.fill_qty > 0:
                    if resp.duplicate:
                        self.log.event("duplicate_order_adopted", client_order_id=cid)
                    self.log.event("fill", client_order_id=cid, price=resp.fill_price, qty=resp.fill_qty)
                    return resp
            if attempt < self.attempts and self.retry_backoff > 0:
                _time.sleep(self.retry_backoff)
        self.log.error("order_failed", client_order_id=cid, attempts=self.attempts)
        return None

    def _enter(self, intent: Intent, candle: Candle, close_ts: datetime) -> None:
        ok, why = self.risk.allow_entry(
            self.trades_today, 1 if self.position is not None else 0, self.day_pnl
        )
        if self.halted:
            ok, why = False, "halted_reconcile_mismatch"
        if close_ts.time() >= self.squareoff:
            ok, why = False, "after_squareoff_time"
        if candle.close < self.min_entry_price:
            ok, why = False, "price_below_min_entry"
        if not ok:
            self.log.event("entry_blocked", reason=why, signal=intent.reason, ts=close_ts.isoformat())
            return

        long_ = intent.action == Action.ENTER_LONG
        sign = 1 if long_ else -1
        side = "BUY" if long_ else "SELL"
        fill_px = self.costs.fill_price(side, candle.close)
        stop = self._round_tick(intent.stop) if intent.stop is not None else None
        risk = None
        if stop is not None:
            risk = (fill_px - stop) * sign
            if risk <= 0:
                self.log.event("entry_blocked", reason="invalid_stop", stop=stop, price=fill_px)
                return

        qty = self.lots * self.lot_size
        cid = f"{self.strategy.name}-{self.symbol}-{close_ts:%Y%m%d%H%M}-ENTRY"
        self.log.event(
            "signal",
            strategy=self.strategy.name,
            direction="LONG" if long_ else "SHORT",
            reason=intent.reason,
            price=candle.close,
            stop=stop,
            ts=close_ts.isoformat(),
        )
        resp = self._send(cid, side, qty, fill_px, "ENTRY", close_ts)
        if resp is None:
            self.log.error("entry_failed", client_order_id=cid)
            return

        fill = resp.fill_price
        if stop is not None:
            risk = (fill - stop) * sign
            if risk <= 0:
                self.log.error("entry_beyond_stop", fill=fill, stop=stop)
                self._flatten_unmanaged(side, resp.fill_qty, fill, close_ts)
                return
        targets = []
        if risk is not None:
            for r, frac in intent.target_rs:
                targets.append(
                    {"r": float(r), "fraction": float(frac), "price": self._round_tick(fill + sign * r * risk), "hit": False}
                )
        self.position = Position(
            side="LONG" if long_ else "SHORT",
            instrument=self.symbol,
            entry_ts=close_ts.isoformat(),
            entry_price=fill,
            initial_qty=resp.fill_qty,
            qty=resp.fill_qty,
            stop=stop,
            stop_kind="INITIAL",
            initial_stop=stop,
            risk=risk,
            targets=targets,
            trail_r=intent.trail_r,
            breakeven_after_first_target=intent.breakeven_after_first_target,
            best_price=fill,
            entry_costs=self.costs.total(side, fill, resp.fill_qty),
            meta={"entry_id": cid, "lot_size": self.lot_size, "reason": intent.reason, "signal": intent.meta},
        )
        self.trades_today += 1
        self.sm.transition(State.IN_POSITION, intent.reason, close_ts.isoformat())
        self.strategy.on_entry(close_ts)
        self.log.event(
            "position_opened",
            direction=self.position.side,
            qty=self.position.qty,
            price=fill,
            stop=stop,
            targets=[t["price"] for t in targets],
        )

    def _flatten_unmanaged(self, entry_side: str, qty: int, fill: float, ts: datetime) -> None:
        exit_side = "SELL" if entry_side == "BUY" else "BUY"
        self._send(f"{self.strategy.name}-{self.symbol}-{ts:%Y%m%d%H%M}-ABORT", exit_side, qty, fill, "EXIT", ts)

    def _touched(self, pos: Position, c: Candle, price: float) -> bool:
        return c.high >= price if pos.is_long else c.low <= price

    def _stop_touched(self, pos: Position, c: Candle) -> bool:
        if pos.stop is None:
            return False
        return c.low <= pos.stop if pos.is_long else c.high >= pos.stop

    def _manage_position(self, c: Candle, close_ts: datetime) -> None:
        pos = self.position
        stop_hit = self._stop_touched(pos, c)
        pending = [t for t in pos.targets if not t["hit"]]
        target_hit = bool(pending) and self._touched(pos, c, pending[0]["price"])

        if stop_hit and (not target_hit or self.same_candle_rule == "stop_first"):
            if stop_hit and target_hit:
                self.log.event("same_candle_rule_applied", rule="stop_first", ts=close_ts.isoformat())
            self._stop_exit(c, close_ts)
            return
        if target_hit:
            if stop_hit:
                self.log.event("same_candle_rule_applied", rule="target_first", ts=close_ts.isoformat())
            self._process_targets(c, close_ts)
            if self.position is None:
                return
            if stop_hit and self._stop_touched(self.position, c):
                self._stop_exit(c, close_ts)
                return
        self._update_trail(c, close_ts)

    def _stop_exit(self, c: Candle, close_ts: datetime) -> None:
        pos = self.position
        px = min(pos.stop, c.open) if pos.is_long else max(pos.stop, c.open)
        if px != pos.stop:
            self.log.event("gap_through_stop", stop=pos.stop, fill_ref=px, ts=close_ts.isoformat())
        self._close_all(px, close_ts, STOP_REASONS.get(pos.stop_kind, "STOP_LOSS"), slip=True)

    def _process_targets(self, c: Candle, close_ts: datetime) -> None:
        pos = self.position
        for idx, t in enumerate(pos.targets, start=1):
            if t["hit"]:
                continue
            if not self._touched(pos, c, t["price"]):
                break
            px = max(t["price"], c.open) if pos.is_long else min(t["price"], c.open)
            t["hit"] = True
            pos.targets_hit += 1
            is_last = all(x["hit"] for x in pos.targets)
            lots_left = pos.qty // pos.meta["lot_size"]
            if is_last or t["fraction"] >= 1.0:
                qty = pos.qty
            else:
                part = int(math.floor(lots_left * t["fraction"] + 0.5))
                part = min(part, lots_left - 1)
                qty = part * pos.meta["lot_size"] if part >= 1 else 0
            if qty <= 0:
                self.log.event("partial_skipped_single_lot", target=idx, lots_left=lots_left)
            else:
                full = qty >= pos.qty
                done = self._exit_leg(qty, px, close_ts, f"TARGET_{idx}", slip=False)
                if done is None:
                    t["hit"] = False
                    pos.targets_hit -= 1
                    self.pending_exit = f"TARGET_{idx}"
                    return
                if full:
                    self._finalize(close_ts)
                    return
            if pos.targets_hit == 1 and pos.breakeven_after_first_target:
                self._move_stop(pos.entry_price + pos.sign * self.breakeven_offset, "BREAKEVEN", close_ts)
        pos.best_price = max(pos.best_price, c.high) if pos.is_long else min(pos.best_price, c.low)

    def _move_stop(self, new_stop: float, kind: str, close_ts: datetime) -> None:
        pos = self.position
        new_stop = self._round_tick(new_stop)
        improves = pos.stop is None or (new_stop > pos.stop if pos.is_long else new_stop < pos.stop)
        if improves:
            old = pos.stop
            pos.stop, pos.stop_kind = new_stop, kind
            self.log.event("modification", what="stop", old=old, new=new_stop, kind=kind, ts=close_ts.isoformat())

    def _update_trail(self, c: Candle, close_ts: datetime) -> None:
        pos = self.position
        pos.best_price = max(pos.best_price, c.high) if pos.is_long else min(pos.best_price, c.low)
        if pos.trail_r is None or pos.risk is None or pos.targets_hit < 1:
            return
        self._move_stop(pos.best_price - pos.sign * float(pos.trail_r) * pos.risk, "TRAIL", close_ts)

    def _time_and_risk_exits(self, c: Candle, close_ts: datetime) -> None:
        pos = self.position
        reason = None
        if self.pending_exit:
            reason = self.pending_exit
        elif self.risk.kill_requested():
            reason = "KILL_SWITCH"
        elif close_ts.time() >= self.squareoff:
            reason = "SQUAREOFF"
        elif self.risk.daily_loss_breached(self.day_pnl + self._unrealized(c.close)):
            reason = "MAX_DAILY_LOSS"
        if reason:
            self._close_all(c.close, close_ts, reason, slip=True)

    def _close_all(self, raw_price: float, ts: datetime, reason: str, slip: bool) -> None:
        pos = self.position
        if pos is None:
            return
        if self._exit_leg(pos.qty, raw_price, ts, reason, slip=slip) is None:
            self.pending_exit = reason
            return
        self._finalize(ts)

    def _exit_leg(self, qty: int, raw_price: float, ts: datetime, reason: str, slip: bool) -> Optional[Dict[str, Any]]:
        pos = self.position
        side = "SELL" if pos.is_long else "BUY"
        px = self.costs.fill_price(side, raw_price) if slip else raw_price
        cid = f"{pos.meta['entry_id']}-X{len(pos.legs) + 1}"
        resp = self._send(cid, side, qty, px, "EXIT", ts)
        if resp is None:
            return None
        fq, fp = resp.fill_qty, resp.fill_price
        exit_costs = self.costs.total(side, fp, fq)
        entry_part = pos.entry_costs * fq / pos.initial_qty
        gross = pos.sign * (fp - pos.entry_price) * fq
        leg = {
            "ts": ts.isoformat(),
            "qty": fq,
            "price": fp,
            "reason": reason,
            "gross": gross,
            "costs": exit_costs + entry_part,
            "net": gross - exit_costs - entry_part,
            "order_id": cid,
        }
        pos.legs.append(leg)
        pos.qty -= fq
        self.log.event("position_reduced", qty=fq, price=fp, reason=reason, remaining=pos.qty)
        if pos.qty > 0 and pos.targets_hit >= 1 and self.sm.state == State.IN_POSITION:
            self.sm.transition(State.PARTIAL_EXIT, reason, ts.isoformat())
        return leg

    def _finalize(self, ts: datetime) -> None:
        pos = self.position
        legs = pos.legs
        net = sum(l["net"] for l in legs)
        gross = sum(l["gross"] for l in legs)
        costs = sum(l["costs"] for l in legs)
        exit_qty = sum(l["qty"] for l in legs)
        exit_price = sum(l["price"] * l["qty"] for l in legs) / exit_qty
        final_target = pos.targets[-1]["price"] if pos.targets else None
        trade = {
            "entry_time": pos.entry_ts,
            "exit_time": ts.isoformat(),
            "direction": pos.side,
            "instrument": pos.instrument,
            "quantity": pos.initial_qty,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "stop_loss": pos.initial_stop,
            "target": final_target,
            "gross_pnl": gross,
            "costs": costs,
            "net_pnl": net,
            "r_multiple": (net / (pos.risk * pos.initial_qty)) if pos.risk else None,
            "exit_reason": legs[-1]["reason"],
            "entry_reason": pos.meta.get("reason"),
            "legs": legs,
        }
        self.trades.append(trade)
        self.realized += net
        self.day_pnl += net
        self.position = None
        self.pending_exit = None
        self.sm.transition(State.FLAT, trade["exit_reason"], ts.isoformat())
        self.strategy.on_trade_closed(ts)
        self.log.event("position_closed", net_pnl=net, exit_reason=trade["exit_reason"], exit_price=exit_price)

    def _sync_state_machine(self, ts: datetime) -> None:
        if self.position is not None:
            return
        pending = self.strategy.has_pending()
        if pending and self.sm.state == State.FLAT:
            self.sm.transition(State.SIGNAL, "setup_found", ts.isoformat())
        elif not pending and self.sm.state == State.SIGNAL:
            self.sm.transition(State.FLAT, "setup_expired", ts.isoformat())

    def _record_equity(self, c: Candle, close_ts: datetime) -> None:
        self.equity.append(
            {
                "ts": close_ts.isoformat(),
                "equity": self.capital + self.realized + self._unrealized(c.close),
                "realized": self.realized,
            }
        )

    def _persist(self) -> None:
        if self.store is None:
            return
        self.store.save(
            {
                "version": SNAPSHOT_VERSION,
                "last_close_ts": self.last_close_ts.isoformat() if self.last_close_ts else None,
                "day": self.day.isoformat() if self.day else None,
                "day_pnl": self.day_pnl,
                "trades_today": self.trades_today,
                "realized": self.realized,
                "halted": self.halted,
                "pending_exit": self.pending_exit,
                "sm": self.sm.to_dict(),
                "position": self.position.to_dict() if self.position else None,
                "strategy": self.strategy.get_state(),
                "broker": self.broker.snapshot(),
                "trades": self.trades,
            }
        )