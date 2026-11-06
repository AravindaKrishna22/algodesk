from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import State


ALLOWED = {
    State.FLAT: {State.SIGNAL, State.IN_POSITION},
    State.SIGNAL: {State.IN_POSITION, State.FLAT},
    State.IN_POSITION: {State.PARTIAL_EXIT, State.FLAT},
    State.PARTIAL_EXIT: {State.FLAT},
}

CONDITIONS = {
    (State.FLAT, State.SIGNAL): "strategy has a candidate signal waiting for confirmation",
    (State.FLAT, State.IN_POSITION): "entry confirmed on candle close and entry order filled",
    (State.SIGNAL, State.IN_POSITION): "confirmation condition met and entry order filled",
    (State.SIGNAL, State.FLAT): "confirmation window expired or filters now fail",
    (State.IN_POSITION, State.PARTIAL_EXIT): "first target hit and part of the quantity exited",
    (State.IN_POSITION, State.FLAT): "stop, exit signal, square-off, risk halt or kill switch exited everything",
    (State.PARTIAL_EXIT, State.FLAT): "remaining quantity exited by target, stop, signal, square-off or kill switch",
}


class IllegalTransition(Exception):
    pass


class TradeStateMachine:
    def __init__(self, state: State = State.FLAT, max_history: int = 1000):
        self._state = State(state)
        self._max_history = max_history
        self.history: List[Dict[str, Any]] = []

    @property
    def state(self) -> State:
        return self._state

    def can_transition(self, new: State) -> bool:
        return State(new) in ALLOWED[self._state]

    def transition(self, new: State, reason: str = "", ts: Optional[str] = None) -> bool:
        new = State(new)
        if new == self._state:
            return False
        if new not in ALLOWED[self._state]:
            raise IllegalTransition(f"{self._state.value} -> {new.value} is not allowed")
        self.history.append(
            {"ts": ts, "from": self._state.value, "to": new.value, "reason": reason}
        )
        if len(self.history) > self._max_history:
            self.history = self.history[-self._max_history:]
        self._state = new
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {"state": self._state.value, "history": list(self.history)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TradeStateMachine":
        sm = cls(State(d.get("state", State.FLAT.value)))
        sm.history = list(d.get("history", []))
        return sm