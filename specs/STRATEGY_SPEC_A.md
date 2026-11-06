# Strategy Specification: Strategy A (HDFC/Reliance/Sensex/Nifty Options)

**Source:** Client video transcript (`000.txt`)
**Instrument:** High-volume Indian equities/indices options (HDFCBANK, Reliance, SENSEX, NIFTY).
**Primary Timeframe:** 2-Minute candles.
**Execution Type:** Discretionary-to-algorithmic scalping (intraday only).

## 1. Instrument and Strike Selection
* **Underlying:** Options (Call/Put). However, to keep the algo engine linear, this implementation trades the **underlying spot price** (or synthetic futures) and maps the direction to Call (LONG) or Put (SHORT).
* **Strike Selection:** The video states "At the Money (ATM)" is preferred. 
* **ATM Calculation:** The strike nearest to the current spot price. For SENSEX (strike step 100), if spot is 73,050, ATM is 73,000.
* **Expiry:** Client uses the current weekly/monthly expiry (video shows 27 Dec expiry on 6 Oct). *ASSUMPTION: The engine assumes continuous liquidity and does not model expiry-day theta decay or rollovers, as this is a directional spot-replay.*

## 2. Indicators
* **SMA High (20):** Simple Moving Average of the High price over 20 periods.
* **SMA Low (20):** Simple Moving Average of the Low price over 20 periods.
* **MACD (12, 26, 9):** Standard MACD (Fast 12, Slow 26, Signal 9) on the Close price.
* **Body Average (20):** 20-period SMA of the absolute candle body size `(Close - Open)`.

## 3. Entry Rules (All Required)
**Time Filter:** No entries before 09:45 AM. No entries after 14:20 PM.
**Long Entry (Call):**
1. MACD Line crosses above the Signal line within the last 2 candles (`macd_cross_lookback = 2`).
2. Current candle is Green (`Close > Open`).
3. The candle body size is NOT double the 20-period average body size (prevents entering on exhausted spikes).
4. At least 50% of the candle's body must be above the SMA(High) line. (V1 @ 04:32).
5. The NEXT candle's high must break above the signal candle's high. (Max wait: 3 candles).
**Short Entry (Put):**
1. MACD Line crosses below the Signal line within the last 2 candles.
2. Current candle is Red (`Close < Open`).
3. Body size is NOT double the 20-period average.
4. At least 50% of the body must be below the SMA(Low) line.
5. The NEXT candle's low must break below the signal candle's low. (Max wait: 3 candles).

## 4. Exit Rules
* **Stop Loss:** Fixed at the SMA(20) Low (for Longs) or SMA(20) High (for Shorts) of the **signal candle**. (V1 @ 06:54).
* **Target 1 (Partial Exit):** 1:1 Risk/Reward. Exit 50% of the position. (V1 @ 07:41).
* **Breakeven Stop:** Immediately after Target 1 is hit, move the stop loss to the entry price (Cost-to-Cost).
* **Target 2 (Final Exit):** 1:2 Risk/Reward. Exit the remaining 50%. (V1 @ 09:00).
* **Trailing Stop:** Once Target 1 is hit, if the price continues to move favorably, trail the stop loss using a 1R trail.
* **Time Square-off:** Hard exit at 15:15 PM.

## 5. Ambiguity Log
| Video Timestamp | Ambiguity | Choice | Why |
| :--- | :--- | :--- | :--- |
| V1 @ 07:34 | "Target should be 1:2" | Implemented as 2R target for the second half. | Standard R-multiple scaling. |
| V1 @ 12:02 | "Don't take put in a call signal" | Algo trades the spot. If SHORT signal fires, Algo sells spot (analogous to buying Put). | Engine uses `signed_qty`, not option premiums. |
| V1 @ 19:13 | "Don't take big candle trade" | Candle body > 2.0x average body is rejected. | `max_body_multiple: 2.0`. |
| V1 @ 20:45 | "No trades after 2:20 PM" | `latest_entry: "14:20"` enforced. | Signal must close before 14:20. |

## 6. Risk Critique & Edge Cases
* **Repainting:** Signals are calculated strictly on the **close** of the candle. They do not repaint.
* **Gaps:** If a gap up/down occurs, the stop loss fills at the `open` price, not the stop price (slippage applied).
* **Whipsaws:** Taking both the SMA touch and the MACD cross means the algo is vulnerable to chop. The "body > 50%" rule helps filter this, but intraday noise can trigger false signals.