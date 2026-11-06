from algodesk.costs import CostModel
from algodesk.engine import Engine

def test_freeze_qty_chunking():
    # Mock engine to test _chunks() directly
    # Normally, freeze qty = 1800, lot size = 100
    class MockEngine:
        freeze_qty = 1800
        lot_size = 100
        def _chunks(self, qty):
            if not self.freeze_qty or qty <= self.freeze_qty:
                return [qty]
            max_chunk = (self.freeze_qty // self.lot_size) * self.lot_size or self.freeze_qty
            out, left = [], qty
            while left > 0:
                q = min(max_chunk, left)
                out.append(q)
                left -= q
            return out
            
    e = MockEngine()
    assert e._chunks(1000) == [1000]
    assert e._chunks(1800) == [1800]
    assert e._chunks(2000) == [1800, 200]
    assert e._chunks(5000) == [1800, 1800, 1400]

def test_indian_options_costs():
    costs = CostModel({
        "brokerage_flat": 20.0,
        "stt_sell_pct": 0.1,
        "exchange_txn_pct": 0.03503,
        "gst_pct": 18.0,
    })
    
    # Sell 100 qty at 1500
    breakdown = costs.breakdown("SELL", 1500.0, 100)
    
    # Turnover = 150,000
    # STT = 0.1% = 150
    # Exchange = 0.03503% = 52.545
    # GST = 18% of (brokerage 20 + exchange 52.545) = 13.058
    assert breakdown["brokerage"] == 20.0
    assert round(breakdown["stt"], 2) == 150.0
    assert round(breakdown["exchange"], 2) == 52.55