

#!/usr/bin/env python3
import logging
from collections.abc import Iterable, Mapping
from typing import Sequence

import requests
import pandas as pd
import yfinance as yf
from requests import HTTPError
from io import StringIO

# ─── Sector Constellations ──────────────────────────────────────────────────
SECTOR_URLS = {
    "Nifty 50":       "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "Bank Nifty":     "https://archives.nseindia.com/content/indices/ind_niftybanklist.csv",
    "Auto":           "https://archives.nseindia.com/content/indices/ind_niftyautolist.csv",
    "Financial Services": "https://archives.nseindia.com/content/indices/ind_niftyfinancialserviceslist.csv",
    "FMCG":           "https://archives.nseindia.com/content/indices/ind_niftyfmcglist.csv",
    "IT":             "https://archives.nseindia.com/content/indices/ind_niftyitlist.csv",
    "Pharma":         "https://archives.nseindia.com/content/indices/ind_niftypharmalist.csv",
    "Oil & Gas":      "https://archives.nseindia.com/content/indices/ind_niftyoilgaslist.csv",
    "PSU Bank":       "https://archives.nseindia.com/content/indices/ind_niftypsubanklist.csv",
    "Realty":         "https://archives.nseindia.com/content/indices/ind_niftyrealtylist.csv",
    "Energy":         "https://archives.nseindia.com/content/indices/ind_niftyenergylist.csv",
    "Infrastructure": "https://archives.nseindia.com/content/indices/ind_niftyinfrastructurelist.csv",
    "Cement":         "https://archives.nseindia.com/content/indices/ind_niftycementlist.csv",
    "Railway":        "https://archives.nseindia.com/content/indices/ind_niftyrailwaylist.csv",
    "Defence":        "https://archives.nseindia.com/content/indices/ind_niftydefencelist.csv",
}

# ─── Thematic Indices ───────────────────────────────────────────────────────
THEMATIC_URLS = {
    "Nifty India Railways PSU":
        "https://www.niftyindices.com/IndexConstituent/ind_niftyIndiaRailwaysPSU_list.csv",
}

# ─── Module Level Defaults ───────────────────────────────────────────────────
FIFTY_TWO_WEEK_WINDOW = 252
DOWNLOAD_LOOKBACK_DAYS = 400
FALLBACK_TICKERS = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
]

logger = logging.getLogger(__name__)

def load_sector_symbols() -> dict[str, list[str]]:
    sectors = {}
    headers = {"User-Agent": "Mozilla/5.0"}

    for sector, url in SECTOR_URLS.items():
        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
        except HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 404:
                continue
            print(f"⚠️ Could not load {sector}: {e}")
            continue
        except Exception as e:
            print(f"⚠️ Could not load {sector}: {e}")
            continue

        df.columns = df.columns.str.strip().str.upper()
        if "SYMBOL" not in df.columns:
            print(f"❌ No SYMBOL column for {sector}: {df.columns.tolist()}")
            continue

        sectors[sector] = [sym + ".NS" for sym in df["SYMBOL"].tolist()]
    return sectors

def load_thematic_symbols(name: str) -> list[str]:
    if name not in THEMATIC_URLS:
        raise ValueError(f"No CSV URL configured for thematic '{name}'")
    resp = requests.get(THEMATIC_URLS[name], headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    df.columns = df.columns.str.strip().str.upper()
    if "SYMBOL" not in df.columns:
        raise RuntimeError(f"CSV for {name} has no SYMBOL column: {df.columns.tolist()}")
    return [sym + ".NS" for sym in df["SYMBOL"].tolist()]

def chunk_list(lst: list[str], size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]


# ─── Streamlit Helper Functions ─────────────────────────────────────────────
def load_symbols() -> dict[str, list[str]]:
    """Load sector and thematic universes keyed by friendly names.

    The returned tickers are *Yahoo Finance* formatted (e.g. ``INFY.NS``) so the
    Streamlit app can feed them directly into :mod:`yfinance`.
    """

    sectors = load_sector_symbols()

    try:
        sectors["Railways PSU"] = load_thematic_symbols("Nifty India Railways PSU")
    except Exception as exc:  # pragma: no cover - defensive for flaky CSV URLs
        logger.warning("Failed loading thematic symbols: %s", exc)

    if not sectors:
        sectors = {"Fallback": FALLBACK_TICKERS}

    return sectors


def get_yahoo_tickers(symbols: Mapping[str, Sequence[str]] | Iterable[str]) -> list[str]:
    """Return a sorted list of deduplicated Yahoo-compatible tickers.

    ``symbols`` may be the mapping produced by :func:`load_symbols` or any
    iterable of raw symbol strings.  The helper normalises each element so it is
    ready for :mod:`yfinance` downloads.
    """

    if isinstance(symbols, Mapping):
        iterables: Iterable[str] = (sym for bucket in symbols.values() for sym in bucket)
    else:
        iterables = symbols

    if isinstance(iterables, str):
        iterables = [iterables]

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in iterables:
        if not raw:
            continue
        sym = str(raw).strip().upper()
        if not sym:
            continue

        if sym.startswith("^"):
            normalised = sym
        elif sym.endswith(".NS"):
            normalised = sym
        else:
            normalised = f"{sym}.NS"

        if normalised not in seen:
            seen.add(normalised)
            ordered.append(normalised)

    ordered.sort()
    return ordered


def fetch_data(tickers: Iterable[str], lookback_days: int = DOWNLOAD_LOOKBACK_DAYS) -> dict[str, pd.DataFrame]:
    """Download daily price history for the supplied ``tickers``.

    The function wraps :func:`yfinance.download` and returns a mapping from
    ticker symbol to its OHLCV :class:`~pandas.DataFrame`.  Each frame is sorted
    chronologically and stripped of empty rows so downstream analysis is
    deterministic.
    """

    uniq = get_yahoo_tickers(tickers)
    if not uniq:
        return {}

    period = f"{max(lookback_days, FIFTY_TWO_WEEK_WINDOW + 5)}d"

    try:
        data = yf.download(
            uniq,
            period=period,
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            progress=False,
        )
    except Exception as exc:  # pragma: no cover - network/runtime safeguard
        logger.error("Failed to download data for %s: %s", uniq, exc)
        return {}

    frames: dict[str, pd.DataFrame] = {}

    if isinstance(data, pd.DataFrame) and not isinstance(data.columns, pd.MultiIndex):
        df = data.copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().dropna(how="all")
        if not df.empty:
            frames[uniq[0]] = df
        return frames

    if not isinstance(data, pd.DataFrame):
        return frames

    for ticker in uniq:
        if ticker not in data:
            continue
        df = data[ticker].copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().dropna(how="all")
        if df.empty:
            continue
        frames[ticker] = df

    return frames


def get_fresh_52week(data: Mapping[str, pd.DataFrame], window: int = FIFTY_TWO_WEEK_WINDOW) -> list[str]:
    """Identify tickers printing a fresh 52-week high.

    A symbol qualifies when the latest session's *High* (and *Close*) exceed the
    maximum high over the trailing ``window`` sessions (excluding today).
    Returns a sorted list of Yahoo-formatted tickers ready for display.
    """

    if not data:
        return []

    fresh: list[str] = []

    for ticker, df in data.items():
        if df is None or df.empty:
            continue

        if not {"High", "Close"}.issubset(df.columns):
            continue

        cleaned = df.dropna(subset=["High", "Close"])
        if cleaned.empty:
            continue

        cleaned = cleaned.sort_index()
        if len(cleaned) < 2:
            continue

        hist = cleaned.iloc[:-1]
        hist_window = hist if len(hist) < window else hist.iloc[-window:]
        if hist_window.empty:
            continue

        trailing_high = hist_window["High"].max()
        if pd.isna(trailing_high):
            continue

        latest = cleaned.iloc[-1]
        today_high = latest["High"]
        today_close = latest["Close"]

        if pd.isna(today_high) or pd.isna(today_close):
            continue

        if today_high > trailing_high and today_close >= trailing_high:
            fresh.append(ticker)

    return sorted(fresh)
