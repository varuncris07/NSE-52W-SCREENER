import streamlit as st
import pandas as pd
from utils import load_symbols, get_yahoo_tickers, fetch_data, get_fresh_52week

st.set_page_config(page_title="NSE 52-Week High Screener")
st.title("🕵️ NSE 52-Week High Screener")

@st.cache
def init_tickers():
    symbols = load_symbols()
    return get_yahoo_tickers(symbols)

all_tickers = init_tickers()

selected = st.multiselect(
    "Select tickers (leave blank to scan all)",
    options=all_tickers,
    default=[]
)
to_scan = selected or all_tickers

if st.button("Run Screener"):
    with st.spinner("Scanning… this may take a minute"):
        data = fetch_data(to_scan)
        fresh = get_fresh_52week(data)

    if fresh:
        st.success(f"🎉 {len(fresh)} fresh 52-week highs!")
        st.dataframe(pd.DataFrame({"Ticker": fresh}))
    else:
        st.info("No 52-week highs found today.")

st.markdown("---")
st.caption("Built with yfinance & Streamlit")
