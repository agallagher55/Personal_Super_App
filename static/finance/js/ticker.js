// Horizontal market-price ticker bar for /finance, modeled on the Yahoo
// Finance style header. Live prices only come from CoinGecko's free
// no-key public API for now, so the watchlist below is crypto-only.
// Stocks/indices (S&P, Dow, VIX, etc.) need a keyed provider behind a
// server-side proxy (see finance/ARCHITECTURE.md) - add them here once
// that lands.
const WATCHLIST = [
  { id: "bitcoin", label: "Bitcoin USD", symbol: "BTC" },
  { id: "ethereum", label: "Ethereum USD", symbol: "ETH" },
  { id: "solana", label: "Solana USD", symbol: "SOL" },
];

const PRICE_URL =
  "https://api.coingecko.com/api/v3/simple/price?ids=" +
  WATCHLIST.map((t) => t.id).join(",") +
  "&vs_currencies=usd&include_24hr_change=true";

function formatPrice(value) {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value >= 1 ? 2 : 4,
    maximumFractionDigits: value >= 1 ? 2 : 6,
  });
}

function formatChange(pct) {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function renderLoading(bar) {
  bar.innerHTML = "";
  for (const ticker of WATCHLIST) {
    const item = document.createElement("div");
    item.className = "ticker-item is-loading";
    item.innerHTML = `
      <div class="ticker-label">${ticker.label}</div>
      <div class="ticker-price">--</div>
      <div class="ticker-change">loading...</div>
    `;
    bar.appendChild(item);
  }
}

function renderError(bar, message) {
  bar.innerHTML = "";
  const item = document.createElement("div");
  item.className = "ticker-item is-error";
  item.style.minWidth = "auto";
  item.innerHTML = `
    <div class="ticker-label">Market prices</div>
    <div class="ticker-price">${message}</div>
  `;
  bar.appendChild(item);
}

function renderPrices(bar, data) {
  bar.innerHTML = "";
  for (const ticker of WATCHLIST) {
    const quote = data[ticker.id];
    const item = document.createElement("div");
    item.className = "ticker-item";

    if (!quote || typeof quote.usd !== "number") {
      item.innerHTML = `
        <div class="ticker-label">${ticker.label}</div>
        <div class="ticker-price">--</div>
      `;
      bar.appendChild(item);
      continue;
    }

    const change = quote.usd_24h_change ?? 0;
    const direction = change > 0 ? "is-up" : change < 0 ? "is-down" : "is-flat";
    const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "—";

    item.innerHTML = `
      <div class="ticker-label">${ticker.label}</div>
      <div class="ticker-price">${formatPrice(quote.usd)}</div>
      <div class="ticker-change ${direction}">${arrow} ${formatChange(change)}</div>
    `;
    bar.appendChild(item);
  }
}

async function loadPrices(bar, updatedEl) {
  renderLoading(bar);
  try {
    const res = await fetch(PRICE_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderPrices(bar, data);
    if (updatedEl) {
      const now = new Date();
      updatedEl.textContent = `Updated ${now.toLocaleTimeString()}`;
    }
  } catch (err) {
    renderError(bar, "Prices unavailable");
    if (updatedEl) updatedEl.textContent = "";
  }
}

export function initTickerBar({ barId = "ticker-bar", refreshId = "ticker-refresh", updatedId = "ticker-updated" } = {}) {
  const bar = document.getElementById(barId);
  if (!bar) return;
  const refreshBtn = document.getElementById(refreshId);
  const updatedEl = document.getElementById(updatedId);

  loadPrices(bar, updatedEl);

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => loadPrices(bar, updatedEl));
  }
}
