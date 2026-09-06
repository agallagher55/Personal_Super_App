// Renders the "Cash Flow" section on /finance from
// GET /finance/cash-flow.json (finance/ARCHITECTURE.md Part A, Phase 4),
// including the click-a-bar-to-see-its-transactions dialog. Self-contained
// like ticker.js/import.js/spending.js - its own window selector, its own
// DOM, no dependency on spending.js beyond sharing charts.js's helpers and
// dashboard.js's escapeHtml.
import { drawIncomeExpenseChart } from "./charts.js";
import { escapeHtml } from "./dashboard.js";

const CASH_FLOW_URL = "/finance/cash-flow.json";
const CASH_FLOW_TX_URL = "/finance/cash-flow-transactions.json";

function cad(value, opts = {}) {
  return value.toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: opts.cents === false ? 0 : 2,
    maximumFractionDigits: opts.cents === false ? 0 : 2,
  });
}

function formatShortDate(iso) {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatMonthTitle(month) {
  const d = new Date(`${month}-01T00:00:00`);
  if (Number.isNaN(d.getTime())) return month;
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function renderStats(data) {
  const incomeEl = document.getElementById("fin-cashflow-income");
  const expenseEl = document.getElementById("fin-cashflow-expense");
  const netEl = document.getElementById("fin-cashflow-net");
  if (incomeEl) incomeEl.textContent = cad(data.income, { cents: false });
  if (expenseEl) expenseEl.textContent = cad(data.expense, { cents: false });
  if (netEl) {
    netEl.textContent = cad(data.net, { cents: false });
    netEl.classList.toggle("fin-stat-value-negative", data.net < 0);
  }
}

// --- Click a bar to see its transactions ---------------------------------

function renderCashFlowTxRows(container, transactions) {
  container.innerHTML = "";
  if (transactions.length === 0) {
    container.innerHTML = `<p class="fin-empty-note">No transactions.</p>`;
    return;
  }
  for (const tx of transactions) {
    const row = document.createElement("div");
    row.className = "fin-category-tx-row";
    row.innerHTML = `
      <span class="fin-category-tx-date">${formatShortDate(tx.date)}</span>
      <span class="fin-category-tx-description">${escapeHtml(tx.description)}</span>
      <span class="fin-category-tx-amount">${cad(tx.amount)}</span>
    `;
    container.appendChild(row);
  }
}

async function openCashFlowTransactions(month, kind) {
  const dialog = document.getElementById("fin-cashflow-tx-dialog");
  if (!dialog) return;

  const title = document.getElementById("fin-cashflow-tx-dialog-title");
  const subtitle = document.getElementById("fin-cashflow-tx-dialog-subtitle");
  const list = document.getElementById("fin-cashflow-tx-list");
  if (title) title.textContent = `${kind === "income" ? "Income" : "Expense"} — ${formatMonthTitle(month)}`;
  if (subtitle) subtitle.textContent = "";
  list.innerHTML = `<p class="fin-empty-note">Loading…</p>`;
  dialog.showModal();

  try {
    const params = new URLSearchParams({ month, kind });
    const res = await fetch(`${CASH_FLOW_TX_URL}?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderCashFlowTxRows(list, data.transactions);
    if (subtitle) {
      const total = data.transactions.reduce((sum, tx) => sum + tx.amount, 0);
      subtitle.textContent = `${data.transactions.length} transaction${data.transactions.length === 1 ? "" : "s"} · ${cad(total)}`;
    }
  } catch (err) {
    list.innerHTML = `<p class="fin-empty-note">Couldn't load transactions (${err.message}).</p>`;
  }
}

function renderChart(byMonth) {
  const canvas = document.getElementById("fin-cashflow-canvas");
  const tooltip = document.getElementById("fin-cashflow-tooltip");
  const empty = document.getElementById("fin-cashflow-empty");
  if (!canvas) return;

  if (byMonth.length === 0) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  canvas.hidden = false;
  if (empty) empty.hidden = true;
  drawIncomeExpenseChart(canvas, tooltip, byMonth, { onBarClick: openCashFlowTransactions });
}

async function loadCashFlow(window_) {
  const res = await fetch(`${CASH_FLOW_URL}?window=${encodeURIComponent(window_)}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function renderCashFlow(window_) {
  let data;
  try {
    data = await loadCashFlow(window_);
  } catch (err) {
    console.warn("finance cash flow: failed to load summary", err);
    return;
  }
  renderStats(data);
  renderChart(data.byMonth);
}

export function initFinanceCashFlow() {
  const select = document.getElementById("fin-cashflow-window");
  if (!select) return;
  renderCashFlow(select.value);
  select.addEventListener("change", () => renderCashFlow(select.value));
}
