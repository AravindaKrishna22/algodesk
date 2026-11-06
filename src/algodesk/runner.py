from __future__ import annotations

import os
import sys
import yaml
import argparse
from datetime import datetime
from typing import Dict, Any, List

from .broker import create_broker
from .costs import CostModel
from .engine import Engine
from .logging_setup import get_event_logger
from .models import Candle
from .reporting import generate_reports
from .risk import RiskManager
from .state_store import JSONStateStore
from .strategies.strategy_a import StrategyA
from .strategies.strategy_b import StrategyB

# Helper to find the project root (ALGODESK folder)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def load_yaml(filename: str) -> Dict[str, Any]:
    config_path = os.path.join(ROOT_DIR, 'config', filename)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _parse_ts(raw: str) -> datetime:
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(raw.split("+")[0])

def load_candles(csv_path: str) -> List[Candle]:
    import csv
    candles = []
    if not os.path.exists(csv_path):
        print(f"Warning: Data file {csv_path} not found. Using empty dataset.")
        return candles
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append(Candle(
                ts=_parse_ts(row["ts"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0))
            ))
    return candles

def setup_system(strategy_name: str, mode: str, data_file: str, out_tag: str):
    settings = load_yaml("settings.yaml")
    instruments = load_yaml("instruments.yaml")
    
    if strategy_name.lower() == "a":
        strat_cfg = settings["strategy_a"]
        strategy = StrategyA(strat_cfg)
        symbol = "HDFCBANK" 
    elif strategy_name.lower() == "b":
        strat_cfg = settings["strategy_b"]
        strategy = StrategyB(strat_cfg)
        symbol = "DEMO"
    else:
        raise ValueError("Unknown strategy")

    settings["symbol"] = symbol
    instrument_meta = instruments.get(symbol, instruments["DEMO"])
    
    broker = create_broker("paper")
    costs = CostModel(settings["costs"], settings["execution"].get("slippage_points", 0.0))
    risk = RiskManager(settings["risk"])
    
    state_dir = os.path.join(ROOT_DIR, settings["paths"]["state_dir"])
    log_dir = os.path.join(ROOT_DIR, settings["paths"]["log_dir"])
    os.makedirs(state_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    
    store = JSONStateStore(os.path.join(state_dir, f"state_{out_tag}.json"))
    logger = get_event_logger(name=f"algodesk_{out_tag}", log_dir=log_dir, console=True, keep_records=True)
    
    engine = Engine(
        strategy=strategy,
        broker=broker,
        costs=costs,
        risk=risk,
        settings=settings,
        instrument=instrument_meta,
        store=store,
        logger=logger
    )
    
    return engine, logger

def run_generate(args):
    engine, logger = setup_system(args.strategy, "generate", args.data, args.tag)
    candles = load_candles(args.data)
    print(f"Loaded {len(candles)} candles. Running engine...")
    
    if args.recover:
        engine.recover()
        
    engine.run(candles)
    
    out_dir = os.path.join(ROOT_DIR, "outputs")
    paths = generate_reports(engine, out_dir, args.tag)
    print(f"Generated reports and signals: {paths}")

def run_backtest(args):
    # In our architecture, backtest uses the exact same path as generate
    run_generate(args)

def run_paper(args):
    engine, logger = setup_system(args.strategy, "paper", args.data, args.tag)
    candles = load_candles(args.data)
    
    print("Starting paper trading (replay mode)...")
    
    if args.recover:
        if engine.recover():
            print("State recovered. Resuming...")
        else:
            print("No state to recover. Starting fresh.")
    else:
        print("Fresh start (no recovery).")
        engine.store.clear()  # Wipe previous state if not recovering
        
    import time
    try:
        for c in candles:
            engine.on_candle(c)
            # 0.5 second delay allows you to manually create the KILL file mid-run
            time.sleep(0.5) 
    except KeyboardInterrupt:
        print("\n[!] Process killed by user (simulated crash).")
        print("State has been safely persisted. Run with --recover to resume.")
        sys.exit(0)

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["backtest", "paper", "generate"], default="backtest")
    p.add_argument("--strategy", choices=["a", "b", "A", "B"], required=True)
    p.add_argument("--data", type=str, required=True, help="Path to CSV data")
    p.add_argument("--tag", type=str, default="test_run", help="Tag for output files")
    p.add_argument("--recover", action="store_true", help="Attempt to recover from state store")
    return p

if __name__ == "__main__":
    args = build_parser().parse_args()
    if args.mode == "backtest":
        run_backtest(args)
    elif args.mode == "paper":
        run_paper(args)
    elif args.mode == "generate":
        run_generate(args)