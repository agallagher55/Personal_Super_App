"""Fetches the /finance ticker bar's watchlist quotes server-side.

Stooq's free, keyless CSV quote endpoint covers crypto, commodities, and
indices from one source, so a single request here backs the whole
watchlist. Fetching server-side (rather than the browser calling Stooq
directly) sidesteps CORS entirely and keeps the pattern consistent with
how fitness/api proxies Google Health and how finance/ARCHITECTURE.md
plans to proxy Plaid.
"""

import csv
import io
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request

STOOQ_URL = "https://stooq.com/q/l/?s={symbols}&f=sd2t2ohlc&h&e=csv"

WATCHLIST = (
    {"symbol": "btcusd", "label": "Bitcoin USD"},
    {"symbol": "xauusd", "label": "Gold (XAU/USD)"},
    {"symbol": "cl.f", "label": "WTI Crude Oil"},
    {"symbol": "^spx", "label": "S&P 500"},
)


def _empty_quote(ticker):
    return {"symbol": ticker["symbol"], "label": ticker["label"], "price": None, "change_pct": None}


def _parse_quote(ticker, row):
    try:
        close = float(row["Close"])
        open_ = float(row["Open"])
    except (KeyError, TypeError, ValueError):
        return _empty_quote(ticker)
    change_pct = ((close - open_) / open_ * 100) if open_ else 0.0
    return {"symbol": ticker["symbol"], "label": ticker["label"], "price": close, "change_pct": change_pct}


def fetch_prices():
    """Returns (status, body) - body is {"prices": [...]} or {"error": ...}."""
    # Stooq's own symbols use "^" for indices (^spx), which isn't a valid
    # raw URL character - quote each symbol so a malformed query doesn't
    # get the whole multi-symbol request rejected.
    symbols = ",".join(urllib.parse.quote(t["symbol"], safe="") for t in WATCHLIST)
    url = STOOQ_URL.format(symbols=symbols)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            text = response.read().decode("utf-8")
    except Exception:
        # Logged server-side (stderr) rather than exposed to the client -
        # print so it shows up in the terminal running backend/server.py
        # when this endpoint fails, since the failure mode (blocked,
        # rate-limited, DNS, TLS...) matters for diagnosing it.
        print("finance_prices.fetch_prices: request to Stooq failed:", file=sys.stderr)
        traceback.print_exc()
        return 502, {"error": "market data provider unavailable"}

    rows_by_symbol = {row["Symbol"].lower(): row for row in csv.DictReader(io.StringIO(text))}
    prices = [
        _parse_quote(ticker, rows_by_symbol[ticker["symbol"].lower()])
        if ticker["symbol"].lower() in rows_by_symbol
        else _empty_quote(ticker)
        for ticker in WATCHLIST
    ]
    return 200, {"prices": prices}
