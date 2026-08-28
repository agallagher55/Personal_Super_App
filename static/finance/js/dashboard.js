// Renders the /finance dashboard template from static/finance/finance-dashboard.json
// (a plain static file for now - fetched client-side, no backend route
// behind it). finance/ARCHITECTURE.md's Plaid sync (Phases 1-4) is what
// eventually replaces that file with a real `/finance/api/*` endpoint;
// this module only touches DASHBOARD_DATA_URL when that happens.
import { drawNetWorthChart, drawDonut } from "./charts.js";

const DASHBOARD_DATA_URL = "/static/finance/finance-dashboard.json";
const HOLDING_PRICES_URL = "/finance/api/holding-prices";
const STOCK_COLOR_SLOTS = 6; // matches --stock-1..--stock-6 in dashboard.css

function sum(items, get) {
  return items.reduce((total, item) => total + get(item), 0);
}

function pct(part, total) {
  return total > 0 ? (part / total) * 100 : 0;
}

function cad(value, opts = {}) {
  return value.toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: opts.cents === false ? 0 : 2,
    maximumFractionDigits: opts.cents === false ? 0 : 2,
  });
}

function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html != null) node.innerHTML = html;
  return node;
}

// A stable symbol -> color mapping (alphabetical, not by current value) so
// a given stock/ETF keeps the same identity color everywhere on the page -
// in its account's mini donut, the aggregate "by stock" donut, and its own
// row's bar - and doesn't get repainted if holdings values shift the sort
// order later (see dataviz skill: "color follows the entity, never rank").
function buildSymbolColors(investmentAccounts) {
  const symbols = [...new Set(investmentAccounts.flatMap((acc) => acc.holdings.map((h) => h.symbol)))].sort();
  const colors = new Map();
  symbols.forEach((symbol, i) => colors.set(symbol, `--stock-${(i % STOCK_COLOR_SLOTS) + 1}`));
  return colors;
}

// One row: label, dollar amount, and a bar showing what % of `total` this
// row makes up. Shared by every section - cash accounts, holdings, debt
// lines, and lines of credit all render through this.
function renderRow(container, { label, sublabel, value, total, colorVar, meta }) {
  const row = el("div", "fin-row");
  const percent = pct(value, total);
  row.innerHTML = `
    <div class="fin-row-top">
      <span class="fin-row-label">${label}${sublabel ? `<span class="fin-row-sublabel">${sublabel}</span>` : ""}</span>
      <span class="fin-row-value">${cad(value)}</span>
    </div>
    <div class="fin-row-bar-track">
      <div class="fin-row-bar-fill" style="width:${percent.toFixed(1)}%; background:var(${colorVar})"></div>
    </div>
    <div class="fin-row-pct">${total > 0 ? percent.toFixed(1) : "0.0"}% of section total${meta ? ` &middot; ${meta}` : ""}</div>
  `;
  container.appendChild(row);
}

function renderSectionTotal(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = cad(value);
}

function renderCash(cashAccounts, cashTotal) {
  const container = document.getElementById("fin-cash-rows");
  container.innerHTML = "";
  for (const account of cashAccounts) {
    renderRow(container, {
      label: account.institution,
      sublabel: account.name,
      value: account.balance,
      total: cashTotal,
      colorVar: "--status-blue",
    });
  }
  renderSectionTotal("fin-cash-total", cashTotal);
}

// Renders one investment account's holdings breakdown - a small donut (only
// when there's more than one holding; a single-holding "distribution" is
// trivially 100%, no chart needed) plus a compact legend, both sharing the
// same fixed per-symbol colors as the row bars below and the aggregate
// "Portfolio by Stock/ETF" donut.
function renderAccountDonut(account, accIndex, symbolColors) {
  if (account.holdings.length <= 1) return;
  const slices = account.holdings.map((h) => ({ label: h.symbol, value: h.value, colorVar: symbolColors.get(h.symbol) }));
  drawDonut(document.getElementById(`fin-account-donut-${accIndex}`), slices, { label: `${account.accountType} holdings` });
  renderLegend(`fin-account-legend-${accIndex}`, slices, account.total, { compact: true });
}

function renderInvestments(investmentAccountTotals, investmentsTotal, symbolColors) {
  const container = document.getElementById("fin-investment-accounts");
  container.innerHTML = "";
  investmentAccountTotals.forEach((account, accIndex) => {
    const card = el(
      "div",
      "fin-account-card",
      `
      <div class="fin-account-card-header">
        <span class="fin-account-type">${account.accountType}</span>
        <span class="fin-account-institution">${account.institution}</span>
        <span class="fin-account-total">${cad(account.total)}</span>
        <span class="fin-account-pct">${pct(account.total, investmentsTotal).toFixed(1)}% of investments</span>
      </div>
    `
    );

    if (account.holdings.length > 1) {
      const donutRow = el("div", "fin-account-donut-row");
      const donutWrap = el("div", "fin-mini-donut-wrap");
      donutWrap.id = `fin-account-donut-${accIndex}`;
      const legend = el("div", "fin-mini-legend");
      legend.id = `fin-account-legend-${accIndex}`;
      donutRow.appendChild(donutWrap);
      donutRow.appendChild(legend);
      card.appendChild(donutRow);
    }

    const holdingsList = el("div", "fin-rows");
    for (const holding of account.holdings) {
      const changeMeta =
        holding.isLivePrice && typeof holding.changePct === "number"
          ? ` &middot; ${holding.changePct > 0 ? "+" : ""}${holding.changePct.toFixed(2)}% today`
          : "";
      renderRow(holdingsList, {
        label: holding.symbol,
        sublabel: holding.name,
        value: holding.value,
        total: account.total,
        colorVar: symbolColors.get(holding.symbol),
        meta: `${holding.shares.toLocaleString()} sh @ ${cad(holding.price)}${changeMeta}`,
      });
    }
    card.appendChild(holdingsList);
    container.appendChild(card);

    renderAccountDonut(account, accIndex, symbolColors);
  });
  renderSectionTotal("fin-investments-total", investmentsTotal);
}

function renderBitcoin(bitcoinHoldings, bitcoinTotal, totalBtc) {
  const container = document.getElementById("fin-bitcoin-rows");
  container.innerHTML = "";
  for (const holding of bitcoinHoldings) {
    renderRow(container, {
      label: holding.location,
      sublabel: `${holding.btc.toFixed(4)} BTC`,
      value: holding.valueCad,
      total: bitcoinTotal,
      colorVar: "--flag",
    });
  }
  renderSectionTotal("fin-bitcoin-total", bitcoinTotal);
  const btcSub = document.getElementById("fin-bitcoin-btc-total");
  if (btcSub) btcSub.textContent = `${totalBtc.toFixed(4)} BTC`;
}

function renderDebt(debt, linesOfCredit, debtTotal) {
  const container = document.getElementById("fin-debt-rows");
  container.innerHTML = "";

  function group(heading, rows) {
    if (rows.length === 0) return;
    const headingEl = el("div", "fin-group-heading", heading);
    container.appendChild(headingEl);
    for (const row of rows) {
      renderRow(container, { ...row, total: debtTotal, colorVar: "--status-red" });
    }
  }

  group(
    "Student Loan",
    debt.studentLoan.map((d) => ({ label: d.name, value: d.balance }))
  );
  group(
    "Credit Cards",
    debt.creditCards.map((d) => ({ label: d.institution, value: d.balance }))
  );
  group(
    "Line of Credit",
    linesOfCredit.filter((l) => l.balance > 0).map((l) => ({ label: l.institution, value: l.balance }))
  );
  group(
    "Bills",
    debt.bills.map((d) => ({ label: d.name, value: d.balance }))
  );

  renderSectionTotal("fin-debt-total", debtTotal);
}

function renderLinesOfCredit(linesOfCredit) {
  const container = document.getElementById("fin-loc-rows");
  container.innerHTML = "";
  const limitTotal = sum(linesOfCredit, (l) => l.limit);
  for (const loc of linesOfCredit) {
    const available = loc.limit - loc.balance;
    const row = el(
      "div",
      "fin-loc-row",
      `
      <div class="fin-row-top">
        <span class="fin-row-label">${loc.institution}<span class="fin-row-sublabel">${loc.interestRate.toFixed(2)}% interest</span></span>
        <span class="fin-row-value">${cad(loc.balance)} <span class="fin-row-sublabel">drawn</span></span>
      </div>
      <div class="fin-row-bar-track">
        <div class="fin-row-bar-fill" style="width:${pct(loc.balance, loc.limit).toFixed(1)}%; background:var(--status-yellow)"></div>
      </div>
      <div class="fin-loc-meta">
        <span>${cad(available)} available</span>
        <span>${cad(loc.limit)} limit &middot; ${pct(loc.limit, limitTotal).toFixed(1)}% of total credit</span>
      </div>
    `
    );
    container.appendChild(row);
  }
  renderSectionTotal("fin-loc-limit-total", limitTotal);
}

function renderLegend(containerId, slices, total, { compact = false } = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  for (const slice of slices) {
    if (!(slice.value > 0)) continue;
    const valueHtml = compact ? "" : `<span class="fin-legend-value">${cad(slice.value, { cents: false })}</span>`;
    const row = el(
      "div",
      compact ? "fin-legend-row fin-legend-row-compact" : "fin-legend-row",
      `
      <span class="fin-legend-swatch" style="background:var(${slice.colorVar})"></span>
      <span class="fin-legend-label">${slice.label}</span>
      ${valueHtml}
      <span class="fin-legend-pct">${pct(slice.value, total).toFixed(1)}%</span>
    `
    );
    container.appendChild(row);
  }
}

function renderSummary({ netWorth, totalAssets, debtTotal }) {
  document.getElementById("fin-stat-net-worth").textContent = cad(netWorth, { cents: false });
  document.getElementById("fin-stat-assets").textContent = cad(totalAssets, { cents: false });
  document.getElementById("fin-stat-debt").textContent = cad(debtTotal, { cents: false });
  const centerValue = document.getElementById("fin-donut-center-value");
  if (centerValue) centerValue.textContent = cad(totalAssets, { cents: false });
}

// Every .section on the page gets a click-to-collapse header, matching the
// arrow + collapsed-state convention static/js/script.js already uses for
// Tasks sections (see static/styles/styles.css's .section-header rules).
function makeSectionsCollapsible() {
  document.querySelectorAll(".section").forEach((section) => {
    const header = section.querySelector(".section-header");
    const body = section.querySelector(".fin-section-body");
    if (!header || !body) return;
    const arrow = el("span", "section-arrow", "&#9660;");
    header.prepend(arrow);
    header.addEventListener("click", () => {
      header.classList.toggle("collapsed");
      body.classList.toggle("collapsed");
    });
  });
}

async function loadDashboardData() {
  const res = await fetch(DASHBOARD_DATA_URL);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// The symbol to look up a live quote under. Most holdings' display symbol
// is directly Yahoo-resolvable, but a handful (TSX-only ETFs like VEQT)
// need an exchange suffix Yahoo requires but the UI shouldn't show - those
// carry an explicit "yahooSymbol" override in finance-dashboard.json.
function holdingLookupSymbol(holding) {
  return holding.yahooSymbol || holding.symbol;
}

// Fetches live prices for every distinct symbol across all holdings via
// backend/finance_prices.py's Yahoo proxy (see ticker.js for the same
// pattern applied to the watchlist sidebar). Failure here - network down,
// Yahoo blocked - degrades to an empty quote map so the dashboard still
// renders with the static prices already in finance-dashboard.json rather
// than breaking the page.
async function loadLivePrices(investmentAccounts) {
  const symbols = [...new Set(investmentAccounts.flatMap((acc) => acc.holdings.map(holdingLookupSymbol)))];
  if (symbols.length === 0) return {};
  try {
    const res = await fetch(`${HOLDING_PRICES_URL}?symbols=${encodeURIComponent(symbols.join(","))}`);
    const data = await res.json();
    if (!res.ok || typeof data.quotes !== "object") throw new Error(data.error || `HTTP ${res.status}`);
    return data.quotes;
  } catch (err) {
    console.warn("finance dashboard: live prices unavailable, using last-known prices from finance-dashboard.json", err);
    return {};
  }
}

// Overlays live quotes onto each holding's static price. A symbol with no
// quote (fetch failed, delisted, missing yahooSymbol suffix) keeps its
// static price from finance-dashboard.json rather than showing nothing.
function applyLivePrices(investmentAccounts, quotes) {
  let liveCount = 0;
  let totalCount = 0;
  const withLivePrices = investmentAccounts.map((acc) => ({
    ...acc,
    holdings: acc.holdings.map((holding) => {
      totalCount++;
      const quote = quotes[holdingLookupSymbol(holding)];
      if (quote && typeof quote.price === "number") {
        liveCount++;
        return { ...holding, price: quote.price, changePct: quote.change_pct, isLivePrice: true };
      }
      return holding;
    }),
  }));
  return { investmentAccounts: withLivePrices, liveCount, totalCount };
}

// Merges same-symbol holdings across every account (e.g. VEQT held in both
// a TFSA and an FHSA) into one total per symbol, for the "what % of the
// overall investment amount does each stock/ETF make up" donut.
function buildStockAggregate(investmentAccountTotals) {
  const totals = new Map();
  for (const account of investmentAccountTotals) {
    for (const holding of account.holdings) {
      const existing = totals.get(holding.symbol);
      if (existing) existing.value += holding.value;
      else totals.set(holding.symbol, { symbol: holding.symbol, name: holding.name, value: holding.value });
    }
  }
  return [...totals.values()].sort((a, b) => b.value - a.value);
}

export async function initFinanceDashboard() {
  const noteEl = document.getElementById("fin-sample-note");
  makeSectionsCollapsible();

  let data;
  try {
    data = await loadDashboardData();
  } catch (err) {
    if (noteEl) {
      noteEl.textContent = `Couldn't load dashboard data (${err.message}).`;
      noteEl.classList.add("fin-banner-error");
    }
    return;
  }

  const { cashAccounts, bitcoinHoldings, linesOfCredit, debt, netWorthHistory } = data;

  if (noteEl) noteEl.textContent = data.note || "";

  const quotes = await loadLivePrices(data.investmentAccounts);
  const { investmentAccounts, liveCount, totalCount } = applyLivePrices(data.investmentAccounts, quotes);

  const pricesUpdatedEl = document.getElementById("fin-prices-updated");
  if (pricesUpdatedEl) {
    if (liveCount === 0) {
      pricesUpdatedEl.textContent = "using last-known prices";
    } else if (liveCount < totalCount) {
      pricesUpdatedEl.textContent = `live prices for ${liveCount}/${totalCount} as of ${new Date().toLocaleTimeString()}`;
    } else {
      pricesUpdatedEl.textContent = `live prices as of ${new Date().toLocaleTimeString()}`;
    }
  }

  const cashTotal = sum(cashAccounts, (a) => a.balance);

  const symbolColors = buildSymbolColors(investmentAccounts);
  const investmentAccountTotals = investmentAccounts.map((acc) => {
    const holdings = acc.holdings
      .map((h) => ({ ...h, value: h.shares * h.price }))
      .sort((a, b) => b.value - a.value); // largest holding first, within each account
    return { ...acc, holdings, total: sum(holdings, (h) => h.value) };
  });
  const investmentsTotal = sum(investmentAccountTotals, (acc) => acc.total);

  const bitcoinTotal = sum(bitcoinHoldings, (b) => b.valueCad);
  const totalBtc = sum(bitcoinHoldings, (b) => b.btc);

  const studentLoanTotal = sum(debt.studentLoan, (d) => d.balance);
  const creditCardsTotal = sum(debt.creditCards, (d) => d.balance);
  const locBalanceTotal = sum(linesOfCredit, (l) => l.balance);
  const billsTotal = sum(debt.bills, (d) => d.balance);
  const debtTotal = studentLoanTotal + creditCardsTotal + locBalanceTotal + billsTotal;

  const totalAssets = cashTotal + investmentsTotal + bitcoinTotal;
  const netWorth = totalAssets - debtTotal;

  renderSummary({ netWorth, totalAssets, debtTotal });

  const allocationSlices = [
    { label: "Cash", value: cashTotal, colorVar: "--status-blue" },
    { label: "Investments", value: investmentsTotal, colorVar: "--status-green" },
    { label: "Bitcoin", value: bitcoinTotal, colorVar: "--flag" },
  ];
  drawDonut(document.getElementById("fin-donut"), allocationSlices, { label: "Asset allocation" });
  renderLegend("fin-allocation-legend", allocationSlices, totalAssets);

  // A breakdown of the "Investments" slice above, one shade per account
  // type instead of a second unrelated hue family - it reads as "this
  // donut is what's inside the green slice."
  const investmentSlices = investmentAccountTotals.map((acc, i) => ({
    label: acc.accountType,
    value: acc.total,
    colorVar: `--invest-${i + 1}`,
  }));
  drawDonut(document.getElementById("fin-investment-donut"), investmentSlices, { label: "Investment breakdown" });
  renderLegend("fin-investment-legend", investmentSlices, investmentsTotal);
  const investDonutCenter = document.getElementById("fin-investment-donut-center-value");
  if (investDonutCenter) investDonutCenter.textContent = cad(investmentsTotal, { cents: false });

  // Aggregate, cross-account view: what % of the whole portfolio does each
  // individual stock/ETF make up (merging e.g. VEQT held in two accounts).
  const stockTotals = buildStockAggregate(investmentAccountTotals);
  const stockSlices = stockTotals.map((s) => ({ label: s.symbol, value: s.value, colorVar: symbolColors.get(s.symbol) }));
  drawDonut(document.getElementById("fin-stock-donut"), stockSlices, { label: "Portfolio by stock/ETF" });
  renderLegend("fin-stock-legend", stockSlices, investmentsTotal);
  const stockDonutCenter = document.getElementById("fin-stock-donut-center-value");
  if (stockDonutCenter) stockDonutCenter.textContent = String(stockTotals.length);

  // The chart's end-dot is drawn as "today," so its value has to match the
  // live-priced net worth in the tile above rather than the static seed
  // value netWorthHistory's last month was scaffolded with - otherwise the
  // two "current net worth" figures disagree as soon as live quotes load.
  const liveNetWorthHistory = netWorthHistory.length
    ? [...netWorthHistory.slice(0, -1), { ...netWorthHistory[netWorthHistory.length - 1], value: netWorth }]
    : netWorthHistory;

  drawNetWorthChart(document.getElementById("fin-networth-canvas"), document.getElementById("fin-networth-tooltip"), liveNetWorthHistory);

  renderCash(cashAccounts, cashTotal);
  renderInvestments(investmentAccountTotals, investmentsTotal, symbolColors);
  renderBitcoin(bitcoinHoldings, bitcoinTotal, totalBtc);
  renderDebt(debt, linesOfCredit, debtTotal);
  renderLinesOfCredit(linesOfCredit);
}
