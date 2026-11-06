from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

from .models import Candle


class HTFResampler:
    def __init__(self, base_minutes: int, htf_minutes: int, session_open: time = time(9, 15)):
        if htf_minutes < base_minutes or htf_minutes % base_minutes != 0:
            raise ValueError("htf_minutes must be a multiple of base_minutes")
        self.base = base_minutes
        self.htf = htf_minutes
        self.session_open = session_open
        self._bucket_start: Optional[datetime] = None
        self._o = self._h = self._l = self._c = None
        self._v = 0.0

    def _bucket_of(self, ts: datetime) -> datetime:
        day_open = datetime.combine(ts.date(), self.session_open)
        minutes = int((ts - day_open).total_seconds() // 60)
        idx = minutes // self.htf
        return day_open + timedelta(minutes=idx * self.htf)

    def _emit(self) -> Candle:
        out = Candle(self._bucket_start, self._o, self._h, self._l, self._c, self._v)
        self._bucket_start = None
        return out

    def update(self, c: Candle) -> Optional[Candle]:
        start = self._bucket_of(c.ts)
        flushed = None
        if self._bucket_start is not None and start != self._bucket_start:
            flushed = self._emit()
        if self._bucket_start is None:
            self._bucket_start = start
            self._o, self._h, self._l, self._c, self._v = c.open, c.high, c.low, c.close, c.volume
        else:
            self._h = max(self._h, c.high)
            self._l = min(self._l, c.low)
            self._c = c.close
            self._v += c.volume
        bucket_end = self._bucket_start + timedelta(minutes=self.htf)
        if c.ts + timedelta(minutes=self.base) >= bucket_end:
            done = self._emit()
            return done if flushed is None else flushed
        return flushed