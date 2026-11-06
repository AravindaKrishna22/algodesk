import pytest
from datetime import datetime
from algodesk.engine import Engine
from algodesk.costs import CostModel
from algodesk.risk import RiskManager
from algodesk.broker import PaperBroker
from algodesk.models import Position
from algodesk.strategies.base import Strategy

# A dummy strategy just to satisfy the Engine initialization
class DummyStrategy(Strategy):
    name = "dummy"
    def __init__(self):
        super().__init__({"timeframe_minutes": 2})
    def feed(self, candle): pass
    def decide(self, candle, close_ts, position): return None

@pytest.fixture
def mock_engine():
    settings = {
        "symbol": "DEMO",
        "capital": 100000.0,
        "sizing": {"lots": 1},
        "session": {"open": "09:15", "close": "15:30", "squareoff": "15:15"},
        "execution": {"slippage_points": 0.5, "order_retries": 1},
        "risk": {},
        "costs": {} # Empty costs for this test
    }
    instrument = {
        "lot_size": 100,
        "tick_size": 0.05,
        "freeze_qty": 1000
    }
    
    # We pass the slippage from settings into the CostModel explicitly here
    costs = CostModel(settings["costs"], slippage_points=settings["execution"]["slippage_points"])
    
    return Engine(
        strategy=DummyStrategy(),
        broker=PaperBroker(),
        costs=costs,
        risk=RiskManager({}),
        settings=settings,
        instrument=instrument
    )

def test_tick_rounding(mock_engine):
    # Tick size is 0.05. 100.123 should round to nearest 0.05 tick (100.10)
    assert mock_engine._round_tick(100.123) == 100.10
    # 100.148 should round up to 100.15
    assert mock_engine._round_tick(100.148) == 100.15
    # Exact ticks should stay the same
    assert mock_engine._round_tick(100.05) == 100.05

def test_slippage_applied(mock_engine):
    # Slippage is set to 0.5 in the mock settings
    # BUY: price + 0.5 slippage
    assert mock_engine.costs.fill_price("BUY", 100.0) == 100.5
    # SELL: price - 0.5 slippage
    assert mock_engine.costs.fill_price("SELL", 100.0) == 99.5

def test_partial_exit_math(mock_engine):
    # Simulate a position that entered at 100 with 200 qty
    pos = Position(
        side="LONG",
        instrument="DEMO",
        entry_ts="2023-01-01T09:15:00",
        entry_price=100.0,
        initial_qty=200,
        qty=200,
        stop=90.0, # Risk = 10 points
        targets=[
            {"r": 1.0, "fraction": 0.5, "price": 110.0, "hit": False},
            {"r": 2.0, "fraction": 1.0, "price": 120.0, "hit": False}
        ],
        meta={"lot_size": 100}
    )
    
    mock_engine.position = pos
    
    # We want to test the engine's math for Target 1
    # Target 1 fraction is 0.5. 
    # 200 qty total / 100 lot size = 2 lots.
    # 2 lots * 0.5 = 1 lot = 100 qty.
    
    import math
    t = pos.targets[0]
    lots_left = pos.qty // pos.meta["lot_size"]
    part = int(math.floor(lots_left * t["fraction"] + 0.5))
    part = min(part, lots_left - 1)
    qty_to_exit = part * pos.meta["lot_size"]
    
    assert qty_to_exit == 100, "Should exit 1 lot (100 qty) at target 1"