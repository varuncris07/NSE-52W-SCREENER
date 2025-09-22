# #!/usr/bin/env python3
# import time
# import schedule
# import yfinance as yf
# from datetime import datetime

# from utils import load_sector_symbols, load_thematic_symbols

# # ─── CONFIG ────────────────────────────────────────────────────────────────
# VOL_THRESH       = 2.5
# INTERVAL         = "5m"
# PERIOD_INTR_DAY  = "1d"
# BREAKOUT_PERIODS = [50, 100, 200, 365]

# # ─── LOAD UNIVERSE ─────────────────────────────────────────────────────────
# sectors = load_sector_symbols()
# try:
#     sectors["Railways PSU"] = load_thematic_symbols("Nifty India Railways PSU")
# except Exception:
#     pass
# SYMBOLS = sorted({s for tickers in sectors.values() for s in tickers})

# # ─── STATE for de-duplication ───────────────────────────────────────────────
# _seen_intraday   = set()
# _seen_breakouts  = {n: set() for n in BREAKOUT_PERIODS}

# # ─── FULL BATCHED SCAN ──────────────────────────────────────────────────────
# def scan_all():
#     now = datetime.now().strftime("%Y-%m-%d %H:%M")
#     print(f"\n[{now}] 🔎 Starting full scan…")

#     # 1) Batch intraday bars for all symbols + index, grouped by ticker
#     intr = yf.download(
#         SYMBOLS + ["^NSEI"],
#         period=PERIOD_INTR_DAY,
#         interval=INTERVAL,
#         group_by="ticker",
#         progress=False,
#         auto_adjust=False
#     )

#     # 2) Batch daily bars for the longest look-back
#     max_n = max(BREAKOUT_PERIODS)
#     daily = yf.download(
#         SYMBOLS,
#         period=f"{max_n+1}d",
#         interval="1d",
#         progress=False,
#         auto_adjust=False
#     )

#     # — Intraday Boost (full-day R) —
#     print(f"\n[{now}] 🔎 Intraday Boost:")
#     idx_df = intr["^NSEI"]
#     if len(idx_df) < 2:
#         print("  no index data yet")
#     else:
#         idx_open  = idx_df["Open"].iloc[0]
#         idx_close = idx_df["Close"].iloc[-1]
#         idx_move  = (idx_close - idx_open) / idx_open
#         if abs(idx_move) < 1e-8:
#             idx_move = 1e-6

#         for sym in SYMBOLS:
#             if sym in _seen_intraday:
#                 continue

#             df = intr[sym]
#             if len(df) < 2:
#                 continue

#             vol_open  = df["Volume"].iloc[0]
#             vol_last  = df["Volume"].iloc[-1]
#             spike     = vol_last / max(vol_open, 1.0)
#             if spike < VOL_THRESH:
#                 continue

#             first_open = df["Open"].iloc[0]
#             last_close = df["Close"].iloc[-1]
#             stock_move = (last_close - first_open) / first_open
#             r_factor   = stock_move / idx_move

#             move_pct = stock_move * 100
#             print(
#                 f"  🚀 {sym:10} | spike={spike:4.2f}× "
#                 f"| stockΔ={move_pct:5.2f}% "
#                 f"| R={r_factor:4.2f}"
#             )
#             _seen_intraday.add(sym)

#     # — Breakout Beacons —
#     latest_bar = intr[SYMBOLS[0]].iloc[-1:]  # we'll use .iloc[-1][sym] below
#     # note: we're just using intr[...] to get timestamp; actual values from daily slice
#     for n in BREAKOUT_PERIODS:
#         print(f"\n[{now}] 🔎 {n}-Day Breakout Beacon:")
#         slice_n = daily.iloc[-(n+1):-1]  # drop today
#         highs   = slice_n["High"].max()
#         lows    = slice_n["Low"].min()

#         for sym in SYMBOLS:
#             if sym in _seen_breakouts[n]:
#                 continue

#             ts = intr[sym].index[-1].strftime("%H:%M")
#             hb = intr[sym]["High"].iloc[-1]
#             lb = intr[sym]["Low"].iloc[-1]
#             ob = intr[sym]["Open"].iloc[-1]
#             cb = intr[sym]["Close"].iloc[-1]

#             if hb > highs[sym]:
#                 dir_, sgn = "bull", (cb - highs[sym]) / highs[sym] * 100
#             elif lb < lows[sym]:
#                 dir_, sgn = "bear", (cb - lows[sym]) / lows[sym] * 100
#             else:
#                 continue

#             pct = (cb - ob) / ob * 100
#             print(f"  {sym:10} | {dir_:>4} | sgn%={sgn:5.2f}% | Δ={pct:5.2f}% | @ {ts}")
#             _seen_breakouts[n].add(sym)

# def main():
#     scan_all()
#     schedule.every(5).minutes.do(scan_all)
#     print(f"\n🔄 Scheduled full scan every 5 minutes.")
#     while True:
#         schedule.run_pending()
#         time.sleep(1)

# if __name__ == "__main__":
#     main()





#!/usr/bin/env python3
import time
import schedule
import logging
from datetime import datetime
from collections import defaultdict

import yfinance as yf
import pandas as pd

from utils import load_sector_symbols, load_thematic_symbols, chunk_list

# ─── CONFIG ────────────────────────────────────────────────────────────────
VOL_THRESH       = 2.5
INTERVAL         = "5m"
PERIOD_INTR_DAY  = "1d"
BREAKOUT_PERIODS = [50, 100, 200, 365]
TIMEOUT          = 20          # seconds for HTTP requests
RETRIES          = 3           # number of retry attempts for downloads
MAX_FAILURES     = 3           # max failures per symbol before skipping
LOG_FILE         = "screener.log"

# ─── SETUP LOGGING ─────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

# ─── LOAD UNIVERSE ─────────────────────────────────────────────────────────
sectors = load_sector_symbols()
try:
    sectors["Railways PSU"] = load_thematic_symbols("Nifty India Railways PSU")
except Exception as e:
    logger.warning(f"Failed loading thematic symbols: {e}")

SYMBOLS = sorted({s for tickers in sectors.values() for s in tickers})
SKIP_SYMBOLS = set()
FAILURE_COUNTS = defaultdict(int)

# ─── DOWNLOAD WITH RETRIES ──────────────────────────────────────────────────
def download_with_retry(symbols, **kwargs):
    for attempt in range(1, RETRIES + 1):
        try:
            data = yf.download(
                symbols,
                **kwargs,
                timeout=TIMEOUT,
                progress=False,
                auto_adjust=False
            )
            return data
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed downloading {symbols}: {e}")
            time.sleep(2 * attempt)
    # After retries, register failures per symbol
    if isinstance(symbols, list):
        for sym in symbols:
            FAILURE_COUNTS[sym] += 1
            if FAILURE_COUNTS[sym] >= MAX_FAILURES:
                SKIP_SYMBOLS.add(sym)
                logger.error(f"Skipping {sym} after {MAX_FAILURES} failures")
    return pd.DataFrame()

# ─── FULL BATCHED SCAN ──────────────────────────────────────────────────────
def scan_all():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n[{now}] 🔎 Starting full scan…")

    # filter out skipped symbols
    active_symbols = [s for s in SYMBOLS if s not in SKIP_SYMBOLS]
    if not active_symbols:
        print("No active symbols to scan.")
        return

    # 1) Intraday data
    intr = download_with_retry(
        active_symbols + ["^NSEI"],
        period=PERIOD_INTR_DAY,
        interval=INTERVAL,
        group_by='ticker'
    )

    # 2) Daily data for breakouts
    max_n = max(BREAKOUT_PERIODS)
    daily = download_with_retry(
        active_symbols,
        period=f"{max_n + 1}d",
        interval="1d"
    )

    # — Intraday Boost —
    print(f"\n[{now}] 🔎 Intraday Boost:")
    if "^NSEI" not in intr or len(intr["^NSEI"]) < 2:
        print("  no index data yet")
    else:
        idx_df = intr["^NSEI"]
        idx_open, idx_close = idx_df["Open"].iloc[0], idx_df["Close"].iloc[-1]
        idx_move = (idx_close - idx_open) / idx_open or 1e-6

        for sym in active_symbols:
            if sym in _seen_intraday:
                continue
            if sym not in intr or len(intr[sym]) < 2:
                continue

            df = intr[sym]
            vol_open, vol_last = df["Volume"].iloc[0], df["Volume"].iloc[-1]
            spike = vol_last / max(vol_open, 1.0)
            if spike < VOL_THRESH:
                continue

            first_open, last_close = df["Open"].iloc[0], df["Close"].iloc[-1]
            stock_move = (last_close - first_open) / first_open
            r_factor = stock_move / idx_move
            move_pct = stock_move * 100

            print(
                f"  🚀 {sym:10} | spike={spike:4.2f}× | stockΔ={move_pct:5.2f}% | R={r_factor:4.2f}"
            )
            _seen_intraday.add(sym)

    # — Breakout Beacons —
    for n in BREAKOUT_PERIODS:
        print(f"\n[{now}] 🔎 {n}-Day Breakout Beacon:")
        if daily.empty or 'High' not in daily:
            print("  no daily data")
            continue

        slice_n = daily.iloc[-(n+1):-1]
        highs = slice_n["High"].max() if isinstance(highs := slice_n["High"], pd.DataFrame) else pd.Series()
        lows = slice_n["Low"].min() if isinstance(lows := slice_n["Low"], pd.DataFrame) else pd.Series()

        for sym in active_symbols:
            if sym in _seen_breakouts[n]:
                continue
            if sym not in intr or intr[sym].empty:
                continue

            ts = intr[sym].index[-1].strftime("%H:%M")
            hb, lb, ob, cb = (
                intr[sym]["High"].iloc[-1],
                intr[sym]["Low"].iloc[-1],
                intr[sym]["Open"].iloc[-1],
                intr[sym]["Close"].iloc[-1]
            )

            if sym not in highs or pd.isna(highs[sym]):
                continue

            if hb > highs[sym]:
                dir_, sgn = "bull", (cb - highs[sym]) / highs[sym] * 100
            elif lb < lows[sym]:
                dir_, sgn = "bear", (cb - lows[sym]) / lows[sym] * 100
            else:
                continue

            pct = (cb - ob) / ob * 100
            print(f"  {sym:10} | {dir_:>4} | sgn%={sgn:5.2f}% | Δ={pct:5.2f}% | @ {ts}")
            _seen_breakouts[n].add(sym)

# ─── STATE for de-duplication ───────────────────────────────────────────────
_seen_intraday = set()
_seen_breakouts = {n: set() for n in BREAKOUT_PERIODS}

# ─── MAIN LOOP ─────────────────────────────────────────────────────────────
def main():
    scan_all()
    schedule.every(5).minutes.do(scan_all)
    print(f"\n🔄 Scheduled full scan every 5 minutes.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
