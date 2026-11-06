# AlgoDesk Trading Engine

A production-grade, event-driven trading engine for Indian markets. Supports directional options scalping (Strategy A) and multi-EMA trend following (Strategy B). The exact same strategy code path is used across **backtest**, **paper trading**, and **live** modes.

## Table of Contents

1. Features
2. Architecture
3. Repository layout
4. Setup
5. First run (step by step)
6. Configuration
7. Running backtests
8. Paper trading
9. Kill switch
10. Crash + recovery
11. Reconcile mismatch
12. Demo evidence
13. Reference results
14. API integration
15. Strategy specifications
16. Edge cases
17. Tests
18. Troubleshooting
19. Recording checklist for submission
20. Requirements

## Features

- **Event-driven engine:** Candle-by-candle replay. Same code path for backtest, paper, and live.
- **Broker agnostic:** Implement `BrokerBase` to plug in Zerodha, Dhan, Angel One, etc. Ships with `PaperBroker`.
- **State persistence:** `JSONStateStore` gives crash recovery (`--recover`) with zero duplicate orders and byte-for-byte identical P&L.
- **Risk controls:** Max daily loss, max trades per day, max open positions, and a file-based kill switch that squares off everything.
- **Config driven:** Session times, sizing, costs, and strategy parameters all live in `config/`.
- **Structured JSON logs:** Every signal, order request, broker response, fill, modification, and error is logged with timestamps.

## Architecture

The engine is decoupled into four layers so that strategies never touch broker APIs, and brokers can be swapped without touching strategy logic.

~~~text
+---------------+       +-------------+       +--------------+
|   Strategy    | ----> |   Engine    | ----> |    Broker    |
|  (decide())   |       |  (on_candle)|       | (place_order)|
+---------------+       +-------------+       +--------------+
         ^                    |                      |
         |                    v                      v
     feed(candle)       RiskManager             PaperBroker
                        CostModel               (or live adapter)
                        StateStore
~~~

Component responsibilities:

1. **`Engine`** - Orchestrates state transitions, risk checks, order placement, and state persistence on every candle.
2. **`Strategy`** - Abstract base class. Implements `feed(candle)` (warm up indicators) and `decide(candle, close_ts, position)` (return `Intent` or `None`).
3. **`BrokerBase`** - Interface for broker APIs. Implements `place_order`, `get_positions`, `snapshot`, `restore`.
4. **`RiskManager`** - Enforces daily loss caps, max trades, max open positions, and kill switch.
5. **`CostModel`** - Applies Indian options costs: brokerage, STT, exchange txn, SEBI, GST, stamp duty, plus slippage.
6. **`JSONStateStore`** - Atomic persistence of full engine state, enabling crash recovery.
7. **`TradeStateMachine`** - Enforces FLAT -> SIGNAL -> IN_POSITION -> PARTIAL_EXIT -> FLAT transitions with illegal-transition guards.

## Repository layout

~~~text
algodesk/
├── config/
│   ├── settings.yaml
│   └── instruments.yaml
├── data/
│   ├── sample_A.csv
│   └── sample_B.csv
├── evidence/
├── logs/
├── outputs/
├── scripts/
│   ├── make_sample_data.py
│   ├── run_backtest.py
│   ├── run_paper.py
│   └── generate_signals.py
├── specs/
│   ├── STRATEGY_SPEC_A.md
│   └── STRATEGY_SPEC_B.md
├── src/algodesk/
│   ├── broker.py
│   ├── costs.py
│   ├── engine.py
│   ├── indicators.py
│   ├── logging_setup.py
│   ├── models.py
│   ├── reporting.py
│   ├── resample.py
│   ├── risk.py
│   ├── runner.py
│   ├── state_machine.py
│   ├── state_store.py
│   └── strategies/
│       ├── base.py
│       ├── strategy_a.py
│       └── strategy_b.py
├── tests/
├── .env.example
├── .gitignore
├── EDGE_CASES.md
├── README.md
└── requirements.txt
~~~

## Setup

### Prerequisites

- **Python 3.10+** (`python --version` should print 3.10 or higher)
- **Git**
- **PowerShell** (Windows) or a POSIX shell (macOS/Linux)

### 1. Clone the repo

~~~bash
git clone <your-private-repo-url> algodesk
cd algodesk
~~~

### 2. Create and activate a virtual environment

**Windows (PowerShell):**

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
~~~

If activation fails with "running scripts is disabled on this system":

~~~powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
~~~

**macOS / Linux:**

~~~bash
python3 -m venv .venv
source .venv/bin/activate
~~~

### 3. Install dependencies

~~~bash
pip install -r requirements.txt
~~~

### 4. Create your `.env` file

~~~powershell
Copy-Item .env.example .env
~~~

Leave API key fields blank for paper mode. Ensure `KILL_SWITCH_FILE=KILL` is present.

## First run (step by step)

### Step 1 - Generate sample data

~~~bash
python scripts/make_sample_data.py
~~~

### Step 2 - Run backtests

~~~bash
python scripts/run_backtest.py --strategy A --data data/sample_A.csv --tag A_run
python scripts/run_backtest.py --strategy B --data data/sample_B.csv --tag B_run
~~~

### Step 3 - Verify reports

Open `outputs/A_run_report.html` and `outputs/B_run_report.html` in a browser.

### Step 4 - Kill switch demo

~~~powershell
Remove-Item state\state_kill_test.json -ErrorAction SilentlyContinue
Remove-Item KILL -ErrorAction SilentlyContinue
python scripts/run_paper.py --strategy A --data data/sample_A.csv --tag kill_test
~~~

Wait for `position_opened`, then:

~~~powershell
New-Item -Path . -Name KILL -ItemType File
~~~

Cleanup:

~~~powershell
Remove-Item KILL
~~~

### Step 5 - Crash + recovery (Strategy A)

~~~powershell
Remove-Item state\state_restart_A.json -ErrorAction SilentlyContinue
python scripts/run_paper.py --strategy A --data data/sample_A.csv --tag restart_A
# Ctrl+C after position_opened
python scripts/run_paper.py --strategy A --data data/sample_A.csv --tag restart_A --recover
~~~

### Step 6 - Crash + recovery (Strategy B)

~~~powershell
Remove-Item state\state_restart_B.json -ErrorAction SilentlyContinue
python scripts/run_paper.py --strategy B --data data/sample_B.csv --tag restart_B
# Ctrl+C after position_opened
python scripts/run_paper.py --strategy B --data data/sample_B.csv --tag restart_B --recover
~~~

### Step 7 - Reconcile mismatch

~~~powershell
Remove-Item state\state_reconcile_test.json -ErrorAction SilentlyContinue
python scripts/run_paper.py --strategy A --data data/sample_A.csv --tag reconcile_test
# Ctrl+C after position_opened
notepad state\state_reconcile_test.json
# Change HDFCBANK qty to 0 and save
python scripts/run_paper.py --strategy A --data data/sample_A.csv --tag reconcile_test --recover
~~~

### Step 8 - Run tests

~~~bash
pytest tests/ -v
~~~

### Step 9 - Save evidence

~~~powershell
New-Item -ItemType Directory -Path evidence -Force
Copy-Item logs\algodesk_kill_test.jsonl      evidence\kill_switch.jsonl      -ErrorAction SilentlyContinue
Copy-Item logs\algodesk_restart_A.jsonl      evidence\restart_A.jsonl        -ErrorAction SilentlyContinue
Copy-Item logs\algodesk_restart_B.jsonl      evidence\restart_B.jsonl        -ErrorAction SilentlyContinue
Copy-Item logs\algodesk_reconcile_test.jsonl evidence\reconcile_mismatch.jsonl -ErrorAction SilentlyContinue
~~~

## Configuration

### config/settings.yaml

~~~yaml
symbol: DEMO
capital: 1000000

session:
  open: "09:15"
  close: "15:30"
  squareoff: "15:15"

sizing:
  lots: 2

risk:
  max_daily_loss: 20000
  max_trades_per_day: 6
  max_open_positions: 1
  kill_switch_file: KILL

execution:
  same_candle_rule: stop_first
  slippage_points: 0.05
  order_retries: 2

costs:
  brokerage_flat: 20.0
  brokerage_pct: 0.03
  stt_sell_pct: 0.1
  exchange_txn_pct: 0.03503
  sebi_per_crore: 10.0
  gst_pct: 18.0
  stamp_buy_pct: 0.003

paths:
  state_dir: state
  log_dir: logs
  output_dir: outputs

strategy_a:
  timeframe_minutes: 2
  sma_length: 20
  macd: { fast: 12, slow: 26, signal: 9 }
  macd_cross_lookback: 2
  min_body_fraction_beyond_band: 0.5
  breakout_window_candles: 3
  body_avg_lookback: 20
  max_body_multiple: 2.0
  earliest_entry: "09:45"
  latest_entry: "14:20"
  cooldown_minutes: 30
  targets:
    - [1.0, 0.5]
    - [2.0, 1.0]
  trail_r: 1.0
  breakeven_after_first_target: true

strategy_b:
  timeframe_minutes: 5
  short_emas: [3, 5, 8, 10, 12, 15]
  long_emas: [30, 35, 40, 45, 50, 60]
  vwma_length: 6
  fast_lines: [vwma, ema3]
  anchor_ema: 60
  earliest_entry: "09:20"
  latest_entry: "15:00"
  protective_stop_pct: 0.5
~~~

### config/instruments.yaml

~~~yaml
DEMO:
  lot_size: 100
  freeze_qty: 1800
  strike_step: 50
  tick_size: 0.05
~~~

## Reference results

| Metric | Strategy A | Strategy B |
|---|---|---|
| Trades | 6 | 5 |
| Win rate | 83.33% | 60.00% |
| Profit factor | 8.34 | 7.39 |
| Net P&L | Rs 2,361.15 | Rs 5,552.09 |
| Return | +0.24% | +0.56% |
| Max drawdown | Rs 725.83 (0.07%) | Rs 1,372.33 (0.14%) |
| Sharpe (daily, rf=0) | 11.04 | 8.39 |
| Total costs | Rs 3,917.85 | Rs 3,041.91 |

## API integration

Adding a live broker requires one class and one registry entry. No changes to any strategy code.

~~~python
class ZerodhaBroker(BrokerBase):
    name = "zerodha"
    def place_order(self, req): ...
    def get_positions(self): ...
    def snapshot(self): ...
    def restore(self, data): ...

BROKERS = {"paper": PaperBroker, "zerodha": ZerodhaBroker}
~~~

~~~text
BROKER_API_KEY=...
BROKER_API_SECRET=...
BROKER_ACCESS_TOKEN=...
~~~

## Strategy specifications

- specs/STRATEGY_SPEC_A.md - HDFC/Reliance/Sensex/Nifty options scalping, every rule cited with video timestamp.
- specs/STRATEGY_SPEC_B.md - Multi-EMA trend following with VWMA anchor, includes ambiguity log.

## Edge cases

See EDGE_CASES.md for all 11 mandatory cases: repainting, lookahead, market hours, expiry day, strike selection, lot size, gaps, freeze quantity, disconnect/reconnect, order rejection, clock drift.

## Tests

~~~bash
pytest tests/ -v
~~~

Coverage: indicators, lookahead, state machine, position sizing, cost model.

## Troubleshooting

- ModuleNotFoundError -> activate venv
- PermissionError on state file -> move out of OneDrive
- FileNotFoundError config -> run from ALGODESK root
- --mode required -> update runner.py build_parser default
- regime None during warmup -> expected for first 60 candles
- Paper too fast -> increase time.sleep in run_paper

## Recording checklist

- Show repo structure
- Run make_sample_data.py
- Run backtest A, open A_run_report.html
- Run backtest B, open B_run_report.html
- Kill switch demo
- Crash + restart demo
- Reconcile mismatch demo
- Run pytest -v
- Show evidence/ folder

## Requirements

- Python 3.10+
- pyyaml>=6.0
- pytest>=7.0

## License & Confidentiality

Client strategy data shared under confidentiality. Do not publish the repo, videos, or strategy rules publicly. Use a private GitHub repository only, and grant access solely to the review team.
