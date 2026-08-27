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
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"

# Bank of Canada's Valet API - free, keyless, official. Used for the Canada
# 5Y yield instead of Yahoo: Yahoo has no working symbol for it (Reuters RIC
# style tickers like "CA5YT=RR" 404 against Yahoo's chart endpoint - that
# naming convention only round-trips for a handful of markets Yahoo covers).
BOC_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json?recent=2"

WATCHLIST = (
    {"symbol": "BTC-USD", "label": "Bitcoin USD"},
    {"symbol": "GC=F", "label": "Gold"},
    {"symbol": "CL=F", "label": "WTI Crude Oil"},
    {"symbol": "^GSPC", "label": "S&P 500"},
    # ^TNX/^TYX's regularMarketPrice is already the actual yield percentage
    # (e.g. 4.65 means 4.65%), not scaled - no adjustment needed.
    {"symbol": "^TNX", "label": "US 10Y Yield", "unit": "percent"},
    {"symbol": "^TYX", "label": "US 30Y Yield", "unit": "percent"},
    {"symbol": "BD.CDN.5YR.DQ.YLD", "label": "Canada 5Y Yield", "unit": "percent", "source": "boc"},
)


def _empty_quote(ticker):
    return {
        "symbol": ticker["symbol"],
        "label": ticker["label"],
        "price": None,
        "change_pct": None,
        "unit": ticker.get("unit", "usd"),
    }


def _fetch_yahoo(ticker):
    url = CHART_URL.format(symbol=urllib.parse.quote(ticker["symbol"], safe=""))
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.load(response)
    meta = data["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")
    return price, previous_close


def _fetch_boc(ticker):
    url = BOC_URL.format(series=urllib.parse.quote(ticker["symbol"], safe=""))
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.load(response)
    observations = data["observations"]
    values = [float(obs[ticker["symbol"]]["v"]) for obs in observations]
    price = values[-1]
    previous_close = values[-2] if len(values) > 1 else None
    return price, previous_close


def _fetch_one(ticker):
    try:
        if ticker.get("source") == "boc":
            price, previous_close = _fetch_boc(ticker)
        else:
            price, previous_close = _fetch_yahoo(ticker)
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


# The watchlist response is identical for every caller, so a short TTL
# cache turns repeat requests within the window into a memory read instead
# of another round trip to Yahoo/BoC. The lock is held for the whole fetch
# (not just the cache check), so callers that arrive while a fetch is
# already in flight - e.g. nav.js's BTC poll and ticker.js's watchlist
# fetch, which fire ~1ms apart on every /finance page load - block on it
# and then get the same result instead of each starting their own fetch.
_PRICES_CACHE_TTL_SECONDS = 45
_prices_cache_lock = threading.Lock()
_prices_cache = {"body": None, "expires_at": 0.0}


def fetch_prices():
    """Returns (status, body). body is always {"prices": [...]}; a ticker
    whose fetch failed comes back with price/change_pct set to None rather
    than failing the whole response."""
    with _prices_cache_lock:
        now = time.monotonic()
        if _prices_cache["body"] is not None and now < _prices_cache["expires_at"]:
            return 200, _prices_cache["body"]

        # Fetch every ticker in parallel rather than looping serially, so
        # total latency is one round trip instead of len(WATCHLIST) of them.
        with ThreadPoolExecutor(max_workers=len(WATCHLIST)) as pool:
            quotes = list(pool.map(_fetch_one, WATCHLIST))
        body = {"prices": quotes}

        _prices_cache["body"] = body
        _prices_cache["expires_at"] = time.monotonic() + _PRICES_CACHE_TTL_SECONDS

        return 200, body


def _fetch_quote(symbol):
    try:
        price, previous_close = _fetch_yahoo({"symbol": symbol})
        change_pct = ((price - previous_close) / previous_close * 100) if previous_close else 0.0
        return {"price": price, "change_pct": change_pct}
    except Exception:
        # Same reasoning as _fetch_one: log server-side, degrade this one
        # symbol to null rather than failing the whole holdings batch - a
        # delisted/renamed/TSX-suffix-missing symbol shouldn't blank the
        # rest of a portfolio's live prices.
        print(f"finance_prices: fetch failed for {symbol}:", file=sys.stderr)
        traceback.print_exc()
        return None


def fetch_holding_quotes(symbols):
    """Fetches live quotes for arbitrary (portfolio holding) symbols, keyed
    by the symbol as passed in. Returns (status, body) where body is
    {"quotes": {symbol: {"price", "change_pct"} | None}}. Unlike the fixed
    WATCHLIST above, callers pass whatever Yahoo-resolvable symbol they
    have (e.g. "VEQT.TO" for a TSX-only ETF) - this just fetches each one
    independently and reports back."""
    if not symbols:
        return 400, {"error": "missing symbols"}
    with ThreadPoolExecutor(max_workers=len(symbols)) as pool:
        quotes = pool.map(_fetch_quote, symbols)
        return 200, {"quotes": dict(zip(symbols, quotes))}
