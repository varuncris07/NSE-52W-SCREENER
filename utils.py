

#!/usr/bin/env python3
import requests
import pandas as pd
from urllib.error import HTTPError
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

def chunk_list(lst: list[str], size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]
