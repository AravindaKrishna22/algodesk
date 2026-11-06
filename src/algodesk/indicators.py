from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple


class SMA:
    def __init__(self, length: int):
        if length < 1:
            raise ValueError("length must be >= 1")
        self.length = length
        self._buf: Deque[float] = deque(maxlen=length)
        self.value: Optional[float] = None

    def update(self, x: float) -> Optional[float]:
        self._buf.append(x)
        if len(self._buf) == self.length:
            self.value = sum(self._buf) / self.length
        else:
            self.value = None
        return self.value


class EMA:
    def __init__(self, length: int):
        if length < 1:
            raise ValueError("length must be >= 1")
        self.length = length
        self.k = 2.0 / (length + 1.0)
        self.value: Optional[float] = None
        self._count = 0
        self._sum = 0.0

    def update(self, x: float) -> Optional[float]:
        if self.value is None:
            self._count += 1
            self._sum += x
            if self._count == self.length:
                self.value = self._sum / self.length
            return self.value
        self.value = x * self.k + self.value * (1.0 - self.k)
        return self.value


class VWMA:
    def __init__(self, length: int):
        if length < 1:
            raise ValueError("length must be >= 1")
        self.length = length
        self._pv: Deque[float] = deque(maxlen=length)
        self._v: Deque[float] = deque(maxlen=length)
        self.value: Optional[float] = None

    def update(self, price: float, volume: float) -> Optional[float]:
        self._pv.append(price * volume)
        self._v.append(volume)
        if len(self._v) < self.length:
            self.value = None
            return None
        total_v = sum(self._v)
        self.value = sum(self._pv) / total_v if total_v > 0 else None
        return self.value


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = EMA(fast)
        self.slow = EMA(slow)
        self.signal = EMA(signal)
        self.value: Optional[Tuple[float, float, float]] = None

    def update(self, close: float) -> Optional[Tuple[float, float, float]]:
        f = self.fast.update(close)
        s = self.slow.update(close)
        if f is None or s is None:
            self.value = None
            return None
        macd_line = f - s
        sig = self.signal.update(macd_line)
        if sig is None:
            self.value = None
            return None
        self.value = (macd_line, sig, macd_line - sig)
        return self.value