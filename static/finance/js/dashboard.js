// Renders the /finance dashboard template from data/finance-dashboard.json
// (a plain static file for now - fetched client-side, no backend route
// behind it). finance/ARCHITECTURE.md's Plaid sync (Phases 1-4) is what
// eventually replaces that file with a real `/finance/api/*` endpoint;
// this module only touches DASHBOARD_DATA_URL when that happens.
import { drawNetWorthChart, drawDonut } from "./charts.js";

const DASHBOARD_DATA_URL = "/data/finance-dashboard.json";

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

// One row: label, dollar amount, and a bar showing what % of `total` this
// row makes up. Shared by every section - cash accounts, holdings, debt
// lines, and lines of credit all render through this.
function renderRow(container, { label, sublabel, value, total, colorVar }) {
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
    <div class="fin-row-pct">${total > 0 ? percent.toFixed(1) : "0.0"}% of section total</div>
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

function renderInvestments(investmentAccountTotals, investmentsTotal) {
  const container = document.getElementById("fin-investment-accounts");
  container.innerHTML = "";
  for (const account of investmentAccountTotals) {
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
    const holdingsList = el("div", "fin-rows");
    for (const holding of account.holdings) {
      renderRow(holdingsList, {
        label: holding.symbol,
        sublabel: holding.name,
        value: holding.value,
        total: account.total,
        colorVar: "--status-green",
      });
    }
    card.appendChild(holdingsList);
    container.appendChild(card);
  }
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

function renderLegend(containerId, slices, total) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  for (const slice of slices) {
    if (!(slice.value > 0)) continue;
    const row = el(
      "div",
      "fin-legend-row",
      `
      <span class="fin-legend-swatch" style="background:var(${slice.colorVar})"></span>
      <span class="fin-legend-label">${slice.label}</span>
      <span class="fin-legend-value">${cad(slice.value, { cents: false })}</span>
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

  const { cashAccounts, investmentAccounts, bitcoinHoldings, linesOfCredit, debt, netWorthHistory } = data;

  if (noteEl) noteEl.textContent = data.note || "";

  const cashTotal = sum(cashAccounts, (a) => a.balance);
  const investmentAccountTotals = investmentAccounts.map((acc) => ({
    ...acc,
    total: sum(acc.holdings, (h) => h.value),
  }));
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
  drawDonut(document.getElementById("fin-donut"), allocationSlices);
  renderLegend("fin-allocation-legend", allocationSlices, totalAssets);

  // A breakdown of the "Investments" slice above, one shade per account
  // type instead of a second unrelated hue family - it reads as "this
  // donut is what's inside the green slice."
  const investmentSlices = investmentAccountTotals.map((acc, i) => ({
    label: acc.accountType,
    value: acc.total,
    colorVar: `--invest-${i + 1}`,
  }));
  drawDonut(document.getElementById("fin-investment-donut"), investmentSlices);
  renderLegend("fin-investment-legend", investmentSlices, investmentsTotal);
  const investDonutCenter = document.getElementById("fin-investment-donut-center-value");
  if (investDonutCenter) investDonutCenter.textContent = cad(investmentsTotal, { cents: false });

  drawNetWorthChart(document.getElementById("fin-networth-canvas"), document.getElementById("fin-networth-tooltip"), netWorthHistory);

  renderCash(cashAccounts, cashTotal);
  renderInvestments(investmentAccountTotals, investmentsTotal);
  renderBitcoin(bitcoinHoldings, bitcoinTotal, totalBtc);
  renderDebt(debt, linesOfCredit, debtTotal);
  renderLinesOfCredit(linesOfCredit);
}
