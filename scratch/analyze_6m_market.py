import sqlite3
from datetime import datetime, timezone
import numpy as np

conn = sqlite3.connect(r'file:data\stage-d-diagnostic.sqlite3?mode=ro', uri=True)
cur = conn.cursor()

# Range: 2026-04-20 to 2026-10-17 (approx 6 months)
start_ts = int(datetime(2026, 4, 20, tzinfo=timezone.utc).timestamp() * 1000)
end_ts = int(datetime(2026, 10, 17, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

rows = cur.execute("""
    SELECT open_time, open, high, low, close, volume 
    FROM klines 
    WHERE symbol='BTCUSDT' AND interval='1d' AND open_time >= ? AND open_time <= ?
    ORDER BY open_time ASC
""", (start_ts, end_ts)).fetchall()

print(f"Total 1d bars in 6 months: {len(rows)}")
if rows:
    opens = [r[1] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    closes = [r[4] for r in rows]
    vols = [r[5] for r in rows]
    
    start_date = datetime.fromtimestamp(rows[0][0]/1000, tz=timezone.utc).strftime('%Y-%m-%d')
    end_date = datetime.fromtimestamp(rows[-1][0]/1000, tz=timezone.utc).strftime('%Y-%m-%d')
    min_price = min(lows)
    max_price = max(highs)
    start_price = opens[0]
    end_price = closes[-1]
    
    # Calculate daily returns
    returns = [np.log(closes[i]/closes[i-1]) for i in range(1, len(closes))]
    daily_vol = np.std(returns) * 100
    ann_vol = daily_vol * np.sqrt(365)
    
    # Max drawdown
    peak = closes[0]
    max_dd = 0
    for c in closes:
        if c > peak: peak = c
        dd = (peak - c) / peak
        if dd > max_dd: max_dd = dd
        
    print(f"Period: {start_date} to {end_date}")
    print(f"Start price: {start_price:.2f}, End price: {end_price:.2f}, Net change: {((end_price/start_price)-1)*100:.2f}%")
    print(f"Min price: {min_price:.2f}, Max price: {max_price:.2f}, Amplitude: {((max_price/min_price)-1)*100:.2f}%")
    print(f"Daily Volatility: {daily_vol:.2f}%, Annualized Volatility: {ann_vol:.2f}%")
    print(f"Max Drawdown: {max_dd*100:.2f}%")

# Let's inspect 15m bars in this 6 months window
count_15m = cur.execute("""
    SELECT count(*) FROM klines 
    WHERE symbol='BTCUSDT' AND interval='15m' AND open_time >= ? AND open_time <= ?
""", (start_ts, end_ts)).fetchone()[0]
print(f"Total 15m bars: {count_15m}")

conn.close()
