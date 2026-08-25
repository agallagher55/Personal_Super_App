// Vertical market-price sidebar for /finance. Prices come from the
// backend's /finance/api/prices proxy (see backend/finance_prices.py),
// which fetches Stooq's free keyless quote endpoint server-side - that
// avoids browser CORS issues and matches how fitness/api proxies Google
// Health. The watchlist itself lives server-side; this just renders
// whatever /finance/api/prices returns, in that order.
const PRICES_URL = "/finance/api/prices";

function formatPrice(value, unit) {
  if (unit === "percent") {
    return `${value.toFixed(2)}%`;
  }
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: value >= 1 ? 2 : 6,
  });
}

function formatChange(pct) {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function renderLoadingItem(label) {
  const item = document.createElement("div");
  item.className = "ticker-item is-loading";
  item.innerHTML = `
    <div class="ticker-label">${label}</div>
    <div class="ticker-price">--</div>
    <div class="ticker-change">loading...</div>
  `;
  return item;
}

function renderLoading(bar, labels) {
  bar.innerHTML = "";
  for (const label of labels) {
    bar.appendChild(renderLoadingItem(label));
  }
}

function renderError(bar, message) {
  bar.innerHTML = "";
  const item = document.createElement("div");
  item.className = "ticker-item is-error";
  item.innerHTML = `
    <div class="ticker-label">Market prices</div>
    <div class="ticker-price">${message}</div>
  `;
  bar.appendChild(item);
}

function renderPrices(bar, prices) {
  bar.innerHTML = "";
  for (const quote of prices) {
    const item = document.createElement("div");
    item.className = "ticker-item";

    if (typeof quote.price !== "number") {
      item.innerHTML = `
        <div class="ticker-label">${quote.label}</div>
        <div class="ticker-price">--</div>
      `;
      bar.appendChild(item);
      continue;
    }

    const change = quote.change_pct ?? 0;
    const direction = change > 0 ? "is-up" : change < 0 ? "is-down" : "is-flat";
    const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "—";

    item.innerHTML = `
      <div class="ticker-label">${quote.label}</div>
      <div class="ticker-price">${formatPrice(quote.price, quote.unit)}</div>
      <div class="ticker-change ${direction}">${arrow} ${formatChange(change)}</div>
    `;
    bar.appendChild(item);
  }
}

async function loadPrices(bar, updatedEl) {
  try {
    const res = await fetch(PRICES_URL);
    const data = await res.json();
    if (!res.ok || !Array.isArray(data.prices)) throw new Error(data.error || `HTTP ${res.status}`);
    renderPrices(bar, data.prices);
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

  renderLoading(bar, ["Loading..."]);
  loadPrices(bar, updatedEl);

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => loadPrices(bar, updatedEl));
  }
}
