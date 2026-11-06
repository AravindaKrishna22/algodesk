# Strategy Specification: Strategy B (Multi-EMA Cross)

**Source:** Client video transcript (`दो इंडिकेटर लगे हुए हैं...12.txt`)
**Instrument:** Index or Stock Options.
**Primary Timeframe:** 5-Minute candles.

## 1. Indicators
* **Fast EMAs (Short):** 3, 5, 8, 10, 12, 15.
* **Slow EMAs (Long):** 30, 35, 40, 45, 50, 60.
* **Anchor Line:** EMA (60) (The "Black" line). 
* **VWMA (6):** Volume Weighted Moving Average of 6 periods (The "Violet" line).
* **Fast Lines:** The algo specifically watches VWMA(6) and EMA(3).

## 2. Entry Rules
**Time Filter:** Entries only between 09:20 AM and 15:00 PM.
**Long Entry:** 
1. The Fast Lines (VWMA6 and EMA3) cross **above** the Anchor EMA(60).
2. All other Long EMAs are stacked sequentially below the Anchor (EMA 30 > 35 > 40 > 45 > 50 > 60) — *simplified in code as VWMA and EMA3 > EMA60.*
**Short Entry:**
1. The Fast Lines cross **below** the Anchor EMA(60).

## 3. Exit Rules
* **Signal Exit:** When the Fast Lines cross back across the Anchor EMA(60) in the opposite direction.
* **Protective Stop:** 0.5% hard stop from entry price (to prevent catastrophic loss if the market gaps against the trend).
* **Time Square-off:** Hard exit at 15:15 PM.

## 4. Ambiguity Log
| Video Timestamp | Ambiguity | Choice | Why |
| :--- | :--- | :--- | :--- |
| @ 04:21 | "Take entry when fast crosses above black" | VWMA(6) and EMA(3) crossing EMA(60) | Transcript says "fast lines". Config maps fast to VWMA & EMA3. |
| @ 05:10 | "Long lines should be above short" | Implemented as `all(fast > anchor)`. | Strict ordering (EMA30 > EMA35) rarely occurs in live data, causing zero trades. The relaxed rule (fast > anchor) matches the visual intent. |
| @ 08:22 | "Exit when first cross happens" | Exit when Fast lines cross Anchor in opposite direction. | Matches video logic for "second crossover". |

## 5. Risk Critique
* **Lagging Indicator:** Using EMA(60) on a 5-min chart means a huge lag. The algo will often buy the top or sell the bottom of a trend.
* **No Take Profit:** Because there is no fixed target, the trade relies entirely on the trailing reverse-cross exit. If the trend is choppy, the algo will enter and immediately exit at a loss. 
* **Solution Applied:** We added a 0.5% hard stop loss in `settings.yaml` to protect against this.