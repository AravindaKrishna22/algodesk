import pytest
from algodesk.indicators import SMA, EMA, MACD

def test_sma():
    sma = SMA(3)
    assert sma.update(10) is None
    assert sma.update(20) is None
    assert sma.update(30) == 20.0
    assert sma.update(40) == 30.0  # (20+30+40)/3

def test_ema():
    ema = EMA(3)
    # k = 2 / (3+1) = 0.5
    assert ema.update(10) is None
    assert ema.update(20) is None
    assert ema.update(30) == 20.0  # (10+20+30)/3
    
    # Next value: 40 * 0.5 + 20.0 * 0.5 = 30.0
    assert ema.update(40) == 30.0

def test_macd():
    macd = MACD(fast=2, slow=4, signal=2)
    # Feed enough data for both EMAs (len 2 and 4) and Signal (len 2) to initialize.
    # Slow EMA(4) needs to update, and Signal needs to update the MACD line.
    for p in [10, 20, 30, 40, 50, 60, 70]:
        result = macd.update(p)
        
    # The final update should return a tuple (macd_line, signal_line, histogram)
    assert result is not None
    assert isinstance(result, tuple)
    assert len(result) == 3