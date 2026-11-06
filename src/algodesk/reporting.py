from __future__ import annotations

import csv
import html
import json
import math
import os
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

SIGNAL_COLUMNS = [
    "datetime",
    "direction",
    "instrument_or_strike",
    "entry_price",
    "stop_loss",
    "target",
    "exit_time",
    "exit_price",
    "exit_reason",
]

TRADE_COLUMNS = [
    "trade_no",
    "entry_time",
    "exit_time",
    "direction",
    "instrument",
    "quantity",
    "entry_price",
    "exit_price",
    "stop_loss",
    "target",
    "gross_pnl",
    "costs",
    "net_pnl",
    "r_multiple",
    "exit_reason",
    "entry_reason",
    "legs",
]

EQUITY_COLUMNS = ["ts", "equity", "drawdown", "drawdown_pct"]

TRADING_DAYS = 252


def _round(x: Optional[float], nd: int = 2) -> Optional[float]:
    return None if x is None else round(float(x), nd)


def _legs_text(trade: Dict[str, Any]) -> str:
    return "|".join(f"{l['reason']}:{l['qty']}@{l['price']:.2f}" for l in trade.get("legs", []))


def drawdown_series(equity: Sequence[Dict[str, Any]], capital: float) -> List[Dict[str, Any]]:
    peak = float(capital)
    out = []
    for p in equity:
        v = float(p["equity"])
        peak = max(peak, v)
        dd = v - peak
        out.append(
            {
                "ts": p["ts"],
                "equity": v,
                "drawdown": dd,
                "drawdown_pct": (dd / peak * 100.0) if peak else 0.0,
            }
        )
    return out


def daily_equity(equity: Sequence[Dict[str, Any]]) -> "OrderedDict[str, float]":
    out: "OrderedDict[str, float]" = OrderedDict()
    for p in equity:
        out[str(p["ts"])[:10]] = float(p["equity"])
    return out


def monthly_returns(equity: Sequence[Dict[str, Any]], capital: float) -> List[Dict[str, Any]]:
    month_end: "OrderedDict[str, float]" = OrderedDict()
    for p in equity:
        month_end[str(p["ts"])[:7]] = float(p["equity"])
    out = []
    prev = float(capital)
    for month, eq in month_end.items():
        pnl = eq - prev
        out.append(
            {
                "month": month,
                "pnl": pnl,
                "return_pct": (pnl / prev * 100.0) if prev else 0.0,
                "end_equity": eq,
            }
        )
        prev = eq
    return out


def _sharpe(daily: "OrderedDict[str, float]", capital: float) -> Optional[float]:
    rets = []
    prev = float(capital)
    for eq in daily.values():
        rets.append((eq - prev) / prev if prev else 0.0)
        prev = eq
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return mean / sd * math.sqrt(TRADING_DAYS)


def _longest_losing_streak(trades: Sequence[Dict[str, Any]]) -> int:
    best = cur = 0
    for t in trades:
        if t["net_pnl"] < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def compute_metrics(
    trades: Sequence[Dict[str, Any]], equity: Sequence[Dict[str, Any]], capital: float
) -> Dict[str, Any]:
    n = len(trades)
    nets = [float(t["net_pnl"]) for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    rs = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    dd = drawdown_series(equity, capital)
    max_dd = -min((d["drawdown"] for d in dd), default=0.0)
    max_dd_pct = -min((d["drawdown_pct"] for d in dd), default=0.0)
    daily = daily_equity(equity)
    net = sum(nets)
    end_equity = float(equity[-1]["equity"]) if equity else float(capital)
    return {
        "start_capital": _round(capital),
        "end_equity": _round(end_equity),
        "period_start": str(equity[0]["ts"])[:10] if equity else None,
        "period_end": str(equity[-1]["ts"])[:10] if equity else None,
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": _round(len(wins) / n * 100.0) if n else None,
        "net_pnl": _round(net),
        "gross_pnl": _round(sum(float(t["gross_pnl"]) for t in trades)),
        "total_costs": _round(sum(float(t["costs"]) for t in trades)),
        "return_pct": _round(net / capital * 100.0) if capital else None,
        "profit_factor": _round(gross_profit / gross_loss) if gross_loss > 0 else None,
        "expectancy": _round(net / n) if n else None,
        "avg_win": _round(gross_profit / len(wins)) if wins else None,
        "avg_loss": _round(-gross_loss / len(losses)) if losses else None,
        "avg_r": _round(sum(rs) / len(rs), 3) if rs else None,
        "best_trade": _round(max(nets)) if nets else None,
        "worst_trade": _round(min(nets)) if nets else None,
        "longest_losing_streak": _longest_losing_streak(trades),
        "max_drawdown": _round(max_dd),
        "max_drawdown_pct": _round(max_dd_pct),
        "sharpe": _round(_sharpe(daily, capital), 3),
    }


def write_signals_csv(trades: Sequence[Dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SIGNAL_COLUMNS)
        for t in trades:
            w.writerow(
                [
                    t["entry_time"],
                    t["direction"],
                    t["instrument"],
                    _round(t["entry_price"]),
                    _round(t["stop_loss"]),
                    _round(t["target"]),
                    t["exit_time"],
                    _round(t["exit_price"]),
                    t["exit_reason"],
                ]
            )


def write_trades_csv(trades: Sequence[Dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TRADE_COLUMNS)
        for i, t in enumerate(trades, start=1):
            w.writerow(
                [
                    i,
                    t["entry_time"],
                    t["exit_time"],
                    t["direction"],
                    t["instrument"],
                    t["quantity"],
                    _round(t["entry_price"]),
                    _round(t["exit_price"]),
                    _round(t["stop_loss"]),
                    _round(t["target"]),
                    _round(t["gross_pnl"]),
                    _round(t["costs"]),
                    _round(t["net_pnl"]),
                    _round(t["r_multiple"], 3),
                    t["exit_reason"],
                    t.get("entry_reason"),
                    _legs_text(t),
                ]
            )


def write_equity_csv(equity: Sequence[Dict[str, Any]], capital: float, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(EQUITY_COLUMNS)
        for d in drawdown_series(equity, capital):
            w.writerow([d["ts"], _round(d["equity"]), _round(d["drawdown"]), _round(d["drawdown_pct"], 3)])


def _money(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:,.2f}"


def _plain(x: Optional[float], suffix: str = "") -> str:
    return "n/a" if x is None else f"{x:g}{suffix}"


def _svg_line(
    values: Sequence[float],
    labels: Sequence[str],
    color: str,
    fill_to_top: bool = False,
    width: int = 920,
    height: int = 250,
) -> str:
    n = len(values)
    if n == 0:
        return "<p>No data.</p>"
    step = max(1, n // 1200)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1.0
    pl, pr, pt, pb = 78, 12, 12, 28
    inner_w, inner_h = width - pl - pr, height - pt - pb

    def x(i: int) -> float:
        return pl + (i / (n - 1) if n > 1 else 0.0) * inner_w

    def y(v: float) -> float:
        return pt + (hi - v) / (hi - lo) * inner_h

    pts = " ".join(f"{x(i):.1f},{y(values[i]):.1f}" for i in idx)
    area = ""
    if fill_to_top:
        poly = f"{x(idx[0]):.1f},{y(hi):.1f} {pts} {x(idx[-1]):.1f},{y(hi):.1f}"
        area = f'<polygon points="{poly}" fill="{color}" fill-opacity="0.18"/>'
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">'
        f'<line x1="{pl}" y1="{pt}" x2="{pl}" y2="{height - pb}" stroke="currentColor" stroke-opacity="0.3"/>'
        f'<line x1="{pl}" y1="{height - pb}" x2="{width - pr}" y2="{height - pb}" stroke="currentColor" stroke-opacity="0.3"/>'
        f'<text x="{pl - 6}" y="{pt + 10}" text-anchor="end" font-size="11" fill="currentColor">{hi:,.0f}</text>'
        f'<text x="{pl - 6}" y="{height - pb}" text-anchor="end" font-size="11" fill="currentColor">{lo:,.0f}</text>'
        f'<text x="{pl}" y="{height - 8}" font-size="11" fill="currentColor">{html.escape(str(labels[0]))}</text>'
        f'<text x="{width - pr}" y="{height - 8}" text-anchor="end" font-size="11" fill="currentColor">'
        f"{html.escape(str(labels[-1]))}</text>"
        f"{area}"
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"/>'
        f"</svg>"
    )


def _metric_cards(m: Dict[str, Any]) -> str:
    items = [
        ("Net P&L", _money(m["net_pnl"])),
        ("Return", _plain(m["return_pct"], "%")),
        ("Max drawdown", f"{_money(m['max_drawdown'])} ({_plain(m['max_drawdown_pct'], '%')})"),
        ("Trades", str(m["trades"])),
        ("Win rate", _plain(m["win_rate_pct"], "%")),
        ("Profit factor", _plain(m["profit_factor"])),
        ("Expectancy / trade", _money(m["expectancy"])),
        ("Average R", _plain(m["avg_r"])),
        ("Avg win / avg loss", f"{_money(m['avg_win'])} / {_money(m['avg_loss'])}"),
        ("Longest losing streak", str(m["longest_losing_streak"])),
        ("Sharpe (daily, rf=0)", _plain(m["sharpe"])),
        ("Total costs", _money(m["total_costs"])),
    ]
    return "".join(
        f'<div class="card"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div></div>'
        for k, v in items
    )


def _monthly_table(rows: Sequence[Dict[str, Any]]) -> str:
    if not rows:
        return "<p>No data.</p>"
    body = "".join(
        f"<tr><td>{r['month']}</td><td class=\"num {'pos' if r['pnl'] >= 0 else 'neg'}\">{_money(r['pnl'])}</td>"
        f"<td class=\"num {'pos' if r['pnl'] >= 0 else 'neg'}\">{r['return_pct']:.2f}%</td></tr>"
        for r in rows
    )
    return f"<table><thead><tr><th>Month</th><th>P&amp;L</th><th>Return</th></tr></thead><tbody>{body}</tbody></table>"


def _trade_table(trades: Sequence[Dict[str, Any]]) -> str:
    if not trades:
        return "<p>No trades.</p>"
    rows = []
    for i, t in enumerate(trades, start=1):
        cls = "pos" if t["net_pnl"] >= 0 else "neg"
        rows.append(
            "<tr>"
            f"<td>{i}</td><td>{html.escape(str(t['entry_time']))}</td><td>{html.escape(str(t['exit_time']))}</td>"
            f"<td>{html.escape(t['direction'])}</td><td class=\"num\">{t['quantity']}</td>"
            f"<td class=\"num\">{t['entry_price']:.2f}</td><td class=\"num\">{t['exit_price']:.2f}</td>"
            f"<td class=\"num {cls}\">{t['net_pnl']:,.2f}</td>"
            f"<td class=\"num\">{'n/a' if t['r_multiple'] is None else format(t['r_multiple'], '.2f')}</td>"
            f"<td>{html.escape(t['exit_reason'])}</td></tr>"
        )
    head = (
        "<thead><tr><th>#</th><th>Entry</th><th>Exit</th><th>Side</th><th>Qty</th><th>Entry px</th>"
        "<th>Exit px</th><th>Net P&amp;L</th><th>R</th><th>Exit reason</th></tr></thead>"
    )
    return f"<div class=\"scroll\"><table>{head}<tbody>{''.join(rows)}</tbody></table></div>"


CSS = """
:root{--bg:#ffffff;--fg:#1c1c1e;--card:#f3f4f6;--line:#d4d4d8;--pos:#15803d;--neg:#b91c1c}
@media (prefers-color-scheme: dark){:root{--bg:#18181b;--fg:#f4f4f5;--card:#27272a;--line:#3f3f46;--pos:#4ade80;--neg:#f87171}}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.45}
main{max-width:980px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:28px 0 8px}
.sub{opacity:.7;font-size:13px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.card{background:var(--card);border-radius:8px;padding:10px 12px}
.k{font-size:12px;opacity:.7}
.v{font-size:17px;font-weight:600;margin-top:2px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}
.neg{color:var(--neg)}
.scroll{overflow-x:auto;max-height:520px;overflow-y:auto}
"""


def write_html_report(
    path: str,
    title: str,
    metrics: Dict[str, Any],
    trades: Sequence[Dict[str, Any]],
    equity: Sequence[Dict[str, Any]],
    capital: float,
    notes: Optional[Sequence[str]] = None,
) -> None:
    dd = drawdown_series(equity, capital)
    labels = [str(p["ts"])[:16].replace("T", " ") for p in equity]
    eq_chart = _svg_line([p["equity"] for p in equity], labels, "#2563eb")
    dd_chart = _svg_line([d["drawdown"] for d in dd], labels, "#dc2626", fill_to_top=True)
    period = f"{metrics['period_start']} to {metrics['period_end']}" if metrics["period_start"] else "no data"
    note_html = ""
    if notes:
        note_html = "<h2>Run settings</h2><ul>" + "".join(f"<li>{html.escape(n)}</li>" for n in notes) + "</ul>"
    doc = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>"
        f"<h1>{html.escape(title)}</h1><div class=\"sub\">{html.escape(period)} | generated "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>"
        f"<div class=\"grid\">{_metric_cards(metrics)}</div>"
        f"<h2>Equity curve</h2>{eq_chart}"
        f"<h2>Drawdown curve</h2>{dd_chart}"
        f"<h2>Monthly returns</h2>{_monthly_table(monthly_returns(equity, capital))}"
        f"<h2>Trade list</h2>{_trade_table(trades)}"
        f"{note_html}"
        "</main></body></html>"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def generate_reports(
    engine: Any, out_dir: str, tag: str, title: Optional[str] = None, notes: Optional[Sequence[str]] = None
) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    trades, equity, capital = engine.trades, engine.equity, float(engine.capital)
    metrics = compute_metrics(trades, equity, capital)
    paths = {
        "signals": os.path.join(out_dir, f"{tag}_signals.csv"),
        "trades": os.path.join(out_dir, f"{tag}_trades.csv"),
        "equity": os.path.join(out_dir, f"{tag}_equity.csv"),
        "metrics": os.path.join(out_dir, f"{tag}_metrics.json"),
        "report": os.path.join(out_dir, f"{tag}_report.html"),
    }
    write_signals_csv(trades, paths["signals"])
    write_trades_csv(trades, paths["trades"])
    write_equity_csv(equity, capital, paths["equity"])
    with open(paths["metrics"], "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    write_html_report(paths["report"], title or f"Backtest report - {tag}", metrics, trades, equity, capital, notes)
    return paths