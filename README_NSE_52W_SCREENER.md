# NSE 52‑Week High Screener

A lightweight NSE (India) stock screener that flags **fresh 52‑week highs** (and potential reversals) from popular sector & thematic indices. The project offers:

- A **Streamlit UI** (`app.py`) for interactive scans.
- A **CLI/cronable scanner** (`screener.py`) that logs intraday breakouts and multi‑lookback breakouts (50/100/200/365 sessions).
- Simple helpers in `utils.py` to fetch & normalize the latest index constituents from NSE/NIfty Indices CSVs.

> ⚠️ **Educational use only.** Market data and symbol universes come from public CSV endpoints and Yahoo Finance via `yfinance`. Double‑check results before trading.

---

## Features

- 🔎 **Fresh 52‑week high detector**: identifies symbols closing above their trailing 52‑week high.
- 🏷️ **Sector & Thematic universes**: pulls Nifty sector baskets (Nifty 50, Bank Nifty, IT, FMCG, etc.) and example thematics like *Nifty India Railways PSU*.
- ⏱️ **Intraday scanning (CLI)**: configurable interval (default 5m) with retries and simple de‑duplication so the same signal isn’t spammed.
- 🧰 **Minimal stack**: `pandas`, `yfinance`, `streamlit`.
- 🧾 **Artifacts**: `screener.log` & `pattern_scanner.log` for console/diagnostics, and CSVs like `sector_breakouts.csv`, `reversal_signals.csv` when present.

---

## Project structure

```
nse-52w-screener/
├─ app.py                 # Streamlit web app for ad‑hoc scans
├─ screener.py            # CLI scanner with scheduling & logging
├─ utils.py               # Loads NSE/NIfty index constituents + small helpers
├─ requirements.txt       # python deps: pandas, yfinance, streamlit
├─ sector_breakouts.csv   # (optional) sample output/checkpoint
├─ reversal_signals.csv   # (optional) sample output/checkpoint
└─ *.log                  # logs written by the scanners
```
> A vendored `venv/` may exist in your archive; **do not commit** it in your own repo.

---

## Quick start

### 1) Create and activate a virtual environment
```bash
python -m venv .venv
# Windows
. .venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 2) Install dependencies
```bash
pip install -r requirements.txt
```

### 3) Run the Streamlit app
```bash
streamlit run app.py
```
Then open the local URL printed in the terminal. Select a sector/thematic universe (or specific tickers) and run a scan for **fresh 52‑week highs**.

### 4) Run the CLI scanner (optional)
The CLI periodically scans the chosen universes and appends results to a log file.

```bash
python screener.py
```
**Defaults** (as implemented in `screener.py`):
- Interval: `5m` (Yahoo Finance)
- Intraday period window: `1d`
- Breakout lookbacks: `[50, 100, 200, 365]` sessions
- Retry/timeout guards around downloads

You can schedule it with `cron`/Task Scheduler for continuous monitoring.

---

## How it works (high level)

- `utils.py`
  - `load_sector_symbols()` – reads NSE index constituent CSVs (e.g., Nifty 50, Bank Nifty, IT, FMCG, …) and returns **Yahoo tickers** (e.g., `TCS.NS`). The module keeps a mapping of friendly sector names to official CSV URLs published by NSE/Nifty Indices.
  - `load_thematic_symbols(name)` – fetches symbols for supported thematics (example: *Nifty India Railways PSU*).
  - `chunk_list(lst, size)` – tiny helper for batching downloads.

- `screener.py`
  - Uses `yfinance` to grab OHLCV for each symbol at a desired interval.
  - Computes rolling highs/lows to check for **fresh 52‑week highs** and prints/logs signals.
  - De‑duplicates alerts so the same symbol/period doesn’t print repeatedly within a session.

- `app.py`
  - Streamlit UI that initializes the **symbol universe** from `utils.py`.
  - Lets you select **all tickers** or a subset and runs a scan to flag **fresh 52‑week highs**.
  - Displays a tidy **DataFrame** of matches with last close, 52‑week high, date of high, sector, etc.

---

## Configuration & customization

Most knobs live at the top of `screener.py`:

```python
VOL_THRESH = 2.5         # (if used) min volume spike threshold
INTERVAL = "5m"          # yfinance interval (e.g., 1m, 5m, 15m, 1h, 1d)
PERIOD_INTR_DAY = "1d"   # intraday history window
BREAKOUT_PERIODS = [50, 100, 200, 365]
TIMEOUT = 20             # HTTP timeout in seconds
RETRIES = 3              # number of download retries
```

To change the **universe**, edit the URL mappings in `utils.py` (`SECTOR_URLS` and `THEMATIC_URLS`) or add your own.

---

## Data sources

- **Index constituents**: Public CSVs from NSE / Nifty Indices (see constant URLs inside `utils.py`).
- **Prices**: Yahoo Finance via `yfinance` (subject to provider limitations, throttling, and symbol coverage).

---

## Troubleshooting

- **NSE CSV 404s** – Some sector CSVs occasionally move or are renamed. `utils.py` is defensive; update URLs if a sector can’t be loaded.
- **Yahoo rate limits** – Large universes with short intervals can hit throttling. Lower the frequency, batch requests, or trim the universe.
- **Mac `__MACOSX` folders** – Safe to ignore; created by Finder zips.
- **Old virtualenv in repo** – Delete `venv/` from version control. Use a fresh `.venv/` locally instead.

---

## Development notes

- Target Python: **3.10+** recommended.
- Code style: keep modules small & imperative; PRs welcome for type hints and docstrings.
- Nice future additions:
  - Dockerfile / devcontainer
  - Configurable universe via YAML
  - E‑mail/Slack notifications on breakouts
  - Caching to reduce re‑downloads

---

## License

MIT (or your preferred license).

---

_This README was generated on 2025-09-21 from the uploaded project structure to document how to set up and use the NSE 52‑Week Screener._
