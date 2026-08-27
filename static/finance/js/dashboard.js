// Renders the /finance dashboard template from static sample data (see
// dashboard-data.js). No network calls here yet - finance/ARCHITECTURE.md's
// Plaid sync (Phases 1-4) is what eventually replaces the imported sample
// arrays with a fetch against a real `/finance/api/*` endpoint; this module
// is written so that swap only touches the imports at the top.
import {
  SAMPLE_DATA_NOTE,
  cashAccounts,
  investmentAccounts,
  bitcoinHoldings,
  linesOfCredit,
  debt,
  netWorthHistory,
} from "./dashboard-data.js";
import { drawNetWorthChart, drawAllocationDonut } from "./charts.js";

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

function renderCash(cashTotal) {
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

function renderInvestments(investmentsTotal) {
  const container = document.getElementById("fin-investment-accounts");
  container.innerHTML = "";
  for (const account of investmentAccounts) {
    const accountTotal = sum(account.holdings, (h) => h.value);
    const card = el(
      "div",
      "fin-account-card",
      `
      <div class="fin-account-card-header">
        <span class="fin-account-type">${account.accountType}</span>
        <span class="fin-account-institution">${account.institution}</span>
        <span class="fin-account-total">${cad(accountTotal)}</span>
        <span class="fin-account-pct">${pct(accountTotal, investmentsTotal).toFixed(1)}% of investments</span>
      </div>
    `
    );
    const holdingsList = el("div", "fin-rows");
    for (const holding of account.holdings) {
      renderRow(holdingsList, {
        label: holding.symbol,
        sublabel: holding.name,
        value: holding.value,
        total: accountTotal,
        colorVar: "--status-green",
      });
    }
    card.appendChild(holdingsList);
    container.appendChild(card);
  }
  renderSectionTotal("fin-investments-total", investmentsTotal);
}

function renderBitcoin(bitcoinTotal, totalBtc) {
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

function renderDebt(debtTotal, locBalanceTotal) {
  const container = document.getElementById("fin-debt-rows");
  container.innerHTML = "";

  function group(heading, rows) {
    if (rows.length === 0) return;
    container.appendChild(el("div", "fin-group-heading", heading));
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
    linesOfCredit
      .filter((l) => l.balance > 0)
      .map((l) => ({ label: l.institution, value: l.balance }))
  );
  group(
    "Bills",
    debt.bills.map((d) => ({ label: d.name, value: d.balance }))
  );

  renderSectionTotal("fin-debt-total", debtTotal);
}

function renderLinesOfCredit() {
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

export function initFinanceDashboard() {
  const cashTotal = sum(cashAccounts, (a) => a.balance);
  const investmentsTotal = sum(investmentAccounts, (acc) => sum(acc.holdings, (h) => h.value));
  const bitcoinTotal = sum(bitcoinHoldings, (b) => b.valueCad);
  const totalBtc = sum(bitcoinHoldings, (b) => b.btc);

  const studentLoanTotal = sum(debt.studentLoan, (d) => d.balance);
  const creditCardsTotal = sum(debt.creditCards, (d) => d.balance);
  const locBalanceTotal = sum(linesOfCredit, (l) => l.balance);
  const billsTotal = sum(debt.bills, (d) => d.balance);
  const debtTotal = studentLoanTotal + creditCardsTotal + locBalanceTotal + billsTotal;

  const totalAssets = cashTotal + investmentsTotal + bitcoinTotal;
  const netWorth = totalAssets - debtTotal;

  const noteEl = document.getElementById("fin-sample-note");
  if (noteEl) noteEl.textContent = SAMPLE_DATA_NOTE;

  renderSummary({ netWorth, totalAssets, debtTotal });

  const allocationSlices = [
    { label: "Cash", value: cashTotal, colorVar: "--status-blue" },
    { label: "Investments", value: investmentsTotal, colorVar: "--status-green" },
    { label: "Bitcoin", value: bitcoinTotal, colorVar: "--flag" },
  ];
  drawAllocationDonut(document.getElementById("fin-donut"), allocationSlices);
  renderLegend("fin-allocation-legend", allocationSlices, totalAssets);

  drawNetWorthChart(document.getElementById("fin-networth-canvas"), document.getElementById("fin-networth-tooltip"), netWorthHistory);

  renderCash(cashTotal);
  renderInvestments(investmentsTotal);
  renderBitcoin(bitcoinTotal, totalBtc);
  renderDebt(debtTotal, locBalanceTotal);
  renderLinesOfCredit();
}
