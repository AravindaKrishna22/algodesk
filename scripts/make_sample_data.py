import csv
import random
import os
from datetime import datetime, timedelta

def generate_data(filename, start_price, days, timeframe_minutes, seed=42):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    random.seed(seed)
    start_day = datetime(2023, 10, 2, 9, 15)
    current_price = start_price

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts", "open", "high", "low", "close", "volume"])
        for d in range(days):
            day_start = start_day + timedelta(days=d)
            if day_start.weekday() >= 5:
                continue
            # Alternate trend: +0.25, +0.25, -0.25, -0.25, +0.25, ...
            trend_bias = 0.25 if (d // 2) % 2 == 0 else -0.25
            t = day_start
            session_end = day_start.replace(hour=15, minute=25)
            while t <= session_end:
                open_p = current_price
                change = random.uniform(-1.0, 1.0) + trend_bias
                close_p = open_p + change
                high_p = max(open_p, close_p) + random.uniform(0, 0.3)
                low_p = min(open_p, close_p) - random.uniform(0, 0.3)
                writer.writerow([
                    t.isoformat(),
                    round(open_p, 2), round(high_p, 2),
                    round(low_p, 2), round(close_p, 2),
                    random.randint(1000, 5000),
                ])
                current_price = close_p
                t += timedelta(minutes=timeframe_minutes)

if __name__ == "__main__":
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    print("Generating 2-min data for Strategy A (3 days, rangey)...")
    generate_data(os.path.join(root, "data", "sample_A.csv"), 1500.0, 3, 2, seed=1)
    print("Generating 5-min data for Strategy B (10 days, alternating trend)...")
    generate_data(os.path.join(root, "data", "sample_B.csv"), 1500.0, 10, 5, seed=2)
    print("Done.")