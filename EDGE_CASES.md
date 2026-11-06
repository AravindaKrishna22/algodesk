# Indian Options Edge Cases Handled

### 01. Repainting
* **Handled:** `Strategy.feed()` and `Strategy.decide()` operate strictly on closed candles. In live mode, the engine's `on_candle()` method only fires when a candle completes. Indicators are updated via `SMA.update()` and `EMA.update()`, which append to a deque/state only once per candle.

### 02. Lookahead
* **Handled:** Higher-timeframe resampling (`HTFResampler`) only flushes a bucket when `c.ts + timedelta(base) >= bucket_end`. The engine never reads the current forming candle's high/low/close during `decide()`; it only reads the previous confirmed state.

### 03. Market Hours
* **Handled:** `Engine.on_candle()` drops any candle where `candle.ts.time() < session_open` or `close_ts.time() > session_close`. The `session_close` is 15:30, and intraday square-off triggers at 15:15 via `_time_and_risk_exits()`.

### 04. Expiry Day
* **Handled (Documented):** The current engine models a linear spot instrument. Expiry rollover (weekly → monthly) and theta decay (near-zero premiums) are **not modeled** because the engine backtests the underlying spot price. The strike selection and expiry choice are handled via `instruments.yaml` and the Strategy A spec. 
* *ASSUMPTION: For the replay, we trade the underlying direction (LONG/SHORT) rather than the option premium.*

### 05. Strike Selection
* **Handled:** For algorithmic purposes, the ATM strike is dynamically chosen via `strategy_a`'s metadata (SMA crossovers are continuous). The config supports `strike_step` in `instruments.yaml`.
* *Missing/Illiquid strikes:* The `PaperBroker` will never reject for liquidity. In `BrokerBase`, a real broker adapter would catch `BrokerError` (liquidity rejection) and retry via `order_retries`.

### 06. Lot Size
* **Handled:** `Engine.__init__` reads `instrument["lot_size"]`. It explicitly raises `ValueError` if `lot_size <= 0`. It is never hardcoded in the strategy. If NSE revises the lot size, you only update `instruments.yaml`.

### 07. Gaps
* **Handled:** In `Engine._stop_exit()`, the code does:
  `px = min(pos.stop, c.open) if pos.is_long else max(pos.stop, c.open)`
  If a gap-down occurs, the exit fills at the `open` price, logging `"gap_through_stop"`, implementing realistic slippage.

### 08. Freeze Quantity
* **Handled:** `Engine._chunks()` splits large orders. If `freeze_qty` is set in `instruments.yaml`, the engine chops the order into lots that respect the freeze limit. E.g., a 200 qty order with a 180 freeze will split into [180, 20], tracking aggregated average fill prices.

### 09. Disconnect and Reconnect
* **Handled:** `JSONStateStore` saves the `TradeStateMachine`, `Position`, `Strategy` state, and `Broker` positions after every candle (`_persist()`). On restart, `Engine.recover()` reloads the state and reconciles the broker positions (`broker.get_positions()`). If there's a mismatch, it halts (`halted = True`).

### 10. Order Rejection
* **Handled:** `Engine._send_one()` uses a `for attempt in range(1, self.attempts + 1)` loop (default 3 attempts). If `broker.place_order()` raises `BrokerError` (e.g., margin, circuit limits), it logs `"broker_error"` and retries. `PaperBroker.reject_next()` and `fail_next()` allow testing this.

### 11. Clock Drift
* **Handled:** All timestamps in the engine are timezone-naive `datetime` objects based on the candle's `ts` (which is exchange time). The engine does not use `datetime.now()` for logic. Clock drift on the host machine will not affect backtests or replays.