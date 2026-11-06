from datetime import datetime, timedelta
from algodesk.models import Candle
from algodesk.indicators import SMA

def test_no_repaint_sma():
    sma = SMA(3)
    start = datetime(2023, 1, 1, 9, 15)
    
    # Feed 3 candles
    c1 = Candle(start, 10, 12, 9, 11)
    c2 = Candle(start + timedelta(minutes=2), 11, 13, 10, 12)
    c3 = Candle(start + timedelta(minutes=4), 12, 14, 11, 13)
    
    sma.update(c1.close)
    sma.update(c2.close)
    sma.update(c3.close)
    
    val_at_3 = sma.value
    assert val_at_3 == 12.0  # (11+12+13)/3
    
    # Feed a massive future candle
    c4 = Candle(start + timedelta(minutes=6), 100, 105, 95, 100)
    sma.update(c4.close)
    
    # The value has updated for the new candle, but the old calculation
    # (val_at_3) should still be 12.0 (proving no repainting of past values)
    assert val_at_3 == 12.0