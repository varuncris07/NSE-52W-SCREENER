#!/usr/bin/env python3
"""CLI scanner that fuses the intraday, breakout and resiliency tasks."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime

import pandas as pd
import schedule
import yfinance as yf

from utils import load_sector_symbols, load_thematic_symbols

# ─── CONFIG ────────────────────────────────────────────────────────────────
VOL_THRESH = 2.5
INTERVAL = "5m"
PERIOD_INTR_DAY = "1d"
BREAKOUT_PERIODS = [50, 100, 200, 365]
TIMEOUT = 20  # seconds for HTTP requests
RETRIES = 3   # number of retry attempts for downloads
MAX_FAILURES = 3
LOG_FILE = "screener.log"
INDEX_SYMBOL = "^NSEI"

# ─── SETUP LOGGING ─────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _build_universe() -> list[str]:
    sectors = load_sector_symbols()
    try:
        sectors["Railways PSU"] = load_thematic_symbols("Nifty India Railways PSU")
    except Exception as exc:  # pragma: no cover - network/HTTP variations
        logger.warning("Failed loading thematic symbols: %s", exc)
    tickers = {symbol for symbols in sectors.values() for symbol in symbols}
    return sorted(tickers)


SYMBOLS = _build_universe()
SKIP_SYMBOLS: set[str] = set()
FAILURE_COUNTS: defaultdict[str, int] = defaultdict(int)

# ─── STATE for de-duplication ───────────────────────────────────────────────
_seen_intraday: set[str] = set()
_seen_breakouts: dict[int, set[str]] = {n: set() for n in BREAKOUT_PERIODS}


def _ensure_multiindex(data: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Normalise yahoo download frames to ticker-first multi-index columns."""

    if data.empty or isinstance(data.columns, pd.MultiIndex):
        return data

    unique_symbols = list(dict.fromkeys(symbols))
    if len(unique_symbols) == 1:
        symbol = unique_symbols[0]
        renamed = data.copy()
        renamed.columns = pd.MultiIndex.from_product([[symbol], renamed.columns])
        return renamed

    return data


def _split_by_symbol(data: pd.DataFrame, requested: list[str]) -> dict[str, pd.DataFrame]:
    """Return a mapping of ticker -> OHLCV frame from a yahoo download."""

    frames: dict[str, pd.DataFrame] = {}
    if data.empty:
        return frames

    if isinstance(data.columns, pd.MultiIndex):
        for ticker in data.columns.get_level_values(0).unique():
            try:
                frame = data.xs(ticker, axis=1, level=0)
            except KeyError:
                continue
            frame = frame.dropna(how="all")
            if not frame.empty:
                frames[ticker] = frame
        return frames

    if requested:
        symbol = requested[0]
        frame = data.dropna(how="all")
        if not frame.empty:
            frames[symbol] = frame
    return frames


def download_with_retry(symbols, *, label: str, **kwargs) -> pd.DataFrame:
    """Download Yahoo Finance data with retries and failure tracking."""

    request = list(dict.fromkeys(symbols))

    for attempt in range(1, RETRIES + 1):
        try:
            data = yf.download(
                request,
                progress=False,
                auto_adjust=False,
                threads=False,
                timeout=TIMEOUT,
                **kwargs,
            )
        except Exception as exc:  # pragma: no cover - yfinance/network variations
            logger.warning("Attempt %d failed downloading %s: %s", attempt, label, exc)
            time.sleep(2 * attempt)
            continue

        if isinstance(data, pd.DataFrame) and not data.empty:
            return _ensure_multiindex(data, request)

        logger.warning("Attempt %d for %s returned no data", attempt, label)
        time.sleep(2 * attempt)

    logger.error("Giving up downloading %s after %d attempts", label, RETRIES)

    for sym in request:
        if sym not in SYMBOLS:
            continue
        FAILURE_COUNTS[sym] += 1
        if FAILURE_COUNTS[sym] >= MAX_FAILURES:
            SKIP_SYMBOLS.add(sym)
            logger.error("Skipping %s after %d failures", sym, MAX_FAILURES)

    return pd.DataFrame()


def _print_and_log(message: str) -> None:
    print(message)
    logger.info(message)


def scan_all() -> None:
    """Run the full intraday + breakout scan."""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    _print_and_log(f"[{now}] 🔎 Starting full scan…")

    active_symbols = [sym for sym in SYMBOLS if sym not in SKIP_SYMBOLS]
    if not active_symbols:
        _print_and_log("No active symbols to scan.")
        return

    intr_frame = download_with_retry(
        active_symbols + [INDEX_SYMBOL],
        label="intraday",
        period=PERIOD_INTR_DAY,
        interval=INTERVAL,
        group_by="ticker",
    )
    intraday = _split_by_symbol(intr_frame, active_symbols + [INDEX_SYMBOL])

    max_lookback = max(BREAKOUT_PERIODS)
    daily_frame = download_with_retry(
        active_symbols,
        label="daily",
        period=f"{max_lookback + 1}d",
        interval="1d",
        group_by="ticker",
    )
    daily = _split_by_symbol(daily_frame, active_symbols)

    # ── Intraday Boost ──────────────────────────────────────────────────────
    _print_and_log(f"[{now}] 🔎 Intraday Boost:")
    idx_df = intraday.get(INDEX_SYMBOL)
    if idx_df is None or len(idx_df) < 2 or not {"Open", "Close"} <= set(idx_df.columns):
        _print_and_log("  no index data yet")
    else:
        idx_open = idx_df["Open"].iloc[0]
        idx_close = idx_df["Close"].iloc[-1]
        idx_move = (idx_close - idx_open) / idx_open if idx_open else 0.0
        if abs(idx_move) < 1e-6:
            idx_move = 1e-6

        for sym in active_symbols:
            if sym in _seen_intraday:
                continue

            sym_intr = intraday.get(sym)
            if sym_intr is None or len(sym_intr) < 2:
                continue
            if not {"Open", "Close", "High", "Low", "Volume"} <= set(sym_intr.columns):
                continue

            vol_open = sym_intr["Volume"].iloc[0]
            vol_last = sym_intr["Volume"].iloc[-1]
            spike = vol_last / max(vol_open, 1.0)
            if spike < VOL_THRESH:
                continue

            first_open = sym_intr["Open"].iloc[0]
            last_close = sym_intr["Close"].iloc[-1]
            if not first_open:
                continue

            stock_move = (last_close - first_open) / first_open
            r_factor = stock_move / idx_move
            move_pct = stock_move * 100

            message = (
                f"  🚀 {sym:10} | spike={spike:4.2f}× | stockΔ={move_pct:5.2f}% | R={r_factor:4.2f}"
            )
            _print_and_log(message)
            _seen_intraday.add(sym)

    # ── Breakout Beacons ────────────────────────────────────────────────────
    for lookback in BREAKOUT_PERIODS:
        _print_and_log(f"[{now}] 🔎 {lookback}-Day Breakout Beacon:")
        emitted = False
        for sym in active_symbols:
            if sym in _seen_breakouts[lookback]:
                continue

            sym_daily = daily.get(sym)
            if sym_daily is None or len(sym_daily) < lookback + 1:
                continue
            if not {"High", "Low", "Open", "Close"} <= set(sym_daily.columns):
                continue

            history = sym_daily.iloc[-(lookback + 1):]
            history = history.dropna(subset=["High", "Low", "Open", "Close"])
            if len(history) < lookback + 1:
                continue

            prior_high = history["High"].iloc[:-1].max()
            prior_low = history["Low"].iloc[:-1].min()
            latest = history.iloc[-1]

            hb = latest["High"]
            lb = latest["Low"]
            ob = latest["Open"]
            cb = latest["Close"]

            direction: str | None = None
            signal_pct = 0.0
            if hb > prior_high:
                direction = "bull"
                signal_pct = (cb - prior_high) / prior_high * 100
            elif lb < prior_low:
                direction = "bear"
                signal_pct = (cb - prior_low) / prior_low * 100

            if direction is None:
                continue

            pct_move = (cb - ob) / ob * 100 if ob else float("nan")
            sym_intr = intraday.get(sym)
            timestamp = (
                sym_intr.index[-1].strftime("%H:%M")
                if sym_intr is not None and not sym_intr.empty
                else "--:--"
            )

            message = (
                f"  {sym:10} | {direction:>4} | sgn%={signal_pct:5.2f}% | Δ={pct_move:5.2f}% | @ {timestamp}"
            )
            _print_and_log(message)
            _seen_breakouts[lookback].add(sym)
            emitted = True

        if not emitted:
            _print_and_log("  no new signals")


def main() -> None:
    scan_all()
    schedule.every(5).minutes.do(scan_all)
    _print_and_log("🔄 Scheduled full scan every 5 minutes.")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
