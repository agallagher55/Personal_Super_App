"""Fetches the /finance page's watchlist quotes server-side.

Uses Yahoo Finance's unofficial (but free, keyless, widely used) chart
endpoint - Stooq's old keyless CSV quote API, tried first, turned out to
be dead (stooq.com itself now 404s that path). Each ticker is fetched
independently so one bad/blocked symbol degrades to "--" for just that
ticker instead of taking the whole watchlist down, the way one malformed
combined request did with Stooq.

Fetching server-side (rather than the browser calling Yahoo directly)
sidesteps CORS entirely and keeps the pattern consistent with how
fitness/api proxies Google Health and how finance/ARCHITECTURE.md plans
to proxy Plaid.
"""

import json
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"

WATCHLIST = (
    {"symbol": "BTC-USD", "label": "Bitcoin USD"},
    {"symbol": "GC=F", "label": "Gold"},
    {"symbol": "CL=F", "label": "WTI Crude Oil"},
    {"symbol": "^GSPC", "label": "S&P 500"},
    # Yahoo/Reuters bond-yield quotes. CBOE's ^TNX/^TYX (and ^FVX/^IRX) are
    # reported at 10x the actual yield - e.g. a quote of 42.80 means 4.28% -
    # so those need `scale: 10` to display the real percentage. Reuters RIC
    # yields like CA5YT=RR already report the true percentage (scale 1).
    {"symbol": "CA5YT=RR", "label": "Canada 5Y Yield", "unit": "percent", "scale": 1},
    {"symbol": "^TNX", "label": "US 10Y Yield", "unit": "percent", "scale": 10},
    {"symbol": "^TYX", "label": "US 30Y Yield", "unit": "percent", "scale": 10},
)


def _empty_quote(ticker):
    return {
        "symbol": ticker["symbol"],
        "label": ticker["label"],
        "price": None,
        "change_pct": None,
        "unit": ticker.get("unit", "usd"),
    }


def _fetch_one(ticker):
    url = CHART_URL.format(symbol=urllib.parse.quote(ticker["symbol"], safe=""))
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.load(response)
        meta = data["chart"]["result"][0]["meta"]
        scale = ticker.get("scale", 1)
        price = meta["regularMarketPrice"] / scale
        previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        previous_close = previous_close / scale if previous_close else None
        change_pct = ((price - previous_close) / previous_close * 100) if previous_close else 0.0
        return {
            "symbol": ticker["symbol"],
            "label": ticker["label"],
            "price": price,
            "change_pct": change_pct,
            "unit": ticker.get("unit", "usd"),
        }
    except Exception:
        # Logged server-side (stderr) rather than exposed to the client -
        # print so it shows up in the terminal running backend/server.py,
        # since the failure mode (blocked, rate-limited, symbol renamed...)
        # matters for diagnosing it.
        print(f"finance_prices: fetch failed for {ticker['symbol']}:", file=sys.stderr)
        traceback.print_exc()
        return _empty_quote(ticker)


def fetch_prices():
    """Returns (status, body). body is always {"prices": [...]}; a ticker
    whose fetch failed comes back with price/change_pct set to None rather
    than failing the whole response."""
    return 200, {"prices": [_fetch_one(ticker) for ticker in WATCHLIST]}
