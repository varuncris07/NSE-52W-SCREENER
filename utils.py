#!/usr/bin/env python3
import logging
from collections.abc import Iterable, Mapping
from io import StringIO

import pandas as pd
import requests
import yfinance as yf
from urllib.error import HTTPError

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


LOGGER = logging.getLogger(__name__)
DEFAULT_LOOKBACK_DAYS = 380
DEFAULT_CHUNK_SIZE = 25

def load_sector_symbols() -> dict[str, list[str]]:
    sectors = {}
    for sector, url in SECTOR_URLS.items():
        try:
            df = pd.read_csv(url)
        except HTTPError as e:
            if getattr(e, "code", None) == 404:
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


def load_symbols(include_thematics: bool = True) -> dict[str, list[str]]:
    """Return the NSE universes configured for the screener.

    Parameters
    ----------
    include_thematics:
        When ``True`` (default) the helper attempts to augment the sector
        universes with any extra thematic baskets declared in
        :data:`THEMATIC_URLS`.  Failures are logged and ignored so the caller
        still receives the sector symbols.
    """

    universes = load_sector_symbols()
    if not include_thematics:
        return universes

    for name in THEMATIC_URLS:
        try:
            universes[name] = load_thematic_symbols(name)
        except Exception as exc:  # pragma: no cover - network/HTTP variations
            LOGGER.warning("Unable to load thematic '%s': %s", name, exc)
    return universes


def get_yahoo_tickers(universe: Mapping[str, Iterable[str]] | Iterable[str]) -> list[str]:
    """Flatten the configured universes into a sorted, de-duplicated ticker list."""

    if isinstance(universe, Mapping):
        iterable = (symbol for symbols in universe.values() for symbol in symbols)
    else:
        iterable = universe

    seen: dict[str, None] = {}
    for symbol in iterable:
        if not symbol:
            continue
        sym = symbol.strip()
        if not sym:
            continue
        # ``dict.fromkeys`` preserves insertion order (Python 3.7+)
        seen.setdefault(sym, None)
    return sorted(seen.keys())


def fetch_data(
    tickers: Iterable[str],
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    interval: str = "1d",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, pd.DataFrame]:
    """Download historical data for the supplied tickers.

    The helper batches requests to Yahoo Finance to avoid excessive query
    strings for very large universes.  Any batch download failures are logged
    and skipped so that partial results are still returned to the caller.
    """

    # Normalise and de-duplicate tickers while preserving user-provided order.
    tickers = [sym.strip() for sym in tickers or [] if sym and sym.strip()]
    ordered_unique: list[str] = list(dict.fromkeys(tickers))
    if not ordered_unique:
        return {}

    results: dict[str, pd.DataFrame] = {}
    for batch in chunk_list(ordered_unique, chunk_size):
        try:
            data = yf.download(
                batch,
                period=f"{lookback_days}d",
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                threads=False,
                progress=False,
            )
        except Exception as exc:  # pragma: no cover - yfinance/network variations
            LOGGER.warning("Failed downloading batch %s: %s", batch, exc)
            continue

        if data.empty:
            continue

        if isinstance(data.columns, pd.MultiIndex):
            for symbol in batch:
                try:
                    df = data.xs(symbol, axis=1, level=0)
                except KeyError:
                    continue
                df = df.dropna(how="all")
                if not df.empty:
                    results[symbol] = df
        else:
            symbol = batch[0]
            df = data.dropna(how="all")
            if not df.empty:
                results[symbol] = df

    return results


def get_fresh_52week(
    price_history: Mapping[str, pd.DataFrame],
    *,
    lookback: int = 252,
    tolerance: float = 1e-6,
) -> list[str]:
    """Return symbols registering a fresh 52-week high.

    A *fresh* high means the most recent bar's high eclipses the prior
    ``lookback`` period high (excluding the latest bar).  The close must also
    finish at or above that previous high to avoid flagging intraday pokes that
    fade before the session ends.
    """

    fresh: list[str] = []
    for symbol, df in price_history.items():
        if df is None or df.empty:
            continue
        if "High" not in df.columns or "Close" not in df.columns:
            continue

        cleaned = df.sort_index().dropna(subset=["High", "Close"])
        if len(cleaned) < 2:
            continue

        window = cleaned.iloc[-lookback:]
        if len(window) < 2:
            continue

        prior_high = window["High"].iloc[:-1].max()
        if pd.isna(prior_high):
            continue

        latest = window.iloc[-1]
        last_high = latest["High"]
        last_close = latest["Close"]
        if pd.isna(last_high) or pd.isna(last_close):
            continue

        if last_high > prior_high * (1 + tolerance) and last_close >= prior_high * (1 - tolerance):
            fresh.append(symbol)

    return sorted(dict.fromkeys(fresh))


def chunk_list(lst: list[str], size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]
