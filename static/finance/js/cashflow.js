// Renders the "Cash Flow" section on /finance from
// GET /finance/cash-flow.json (finance/ARCHITECTURE.md Part A, Phase 4),
// including the click-a-bar-to-see-its-transactions dialog. Self-contained
// like ticker.js/import.js/spending.js - its own window selector, its own
// DOM, no dependency on spending.js beyond sharing charts.js's helpers and
// dashboard.js's escapeHtml.
import { drawIncomeExpenseChart } from "./charts.js";
import { escapeHtml, renderLegend } from "./dashboard.js";

// Cyclic color assignment for the "by type" breakdown - same "reuse the
// --stock-1..12 identity-color family" reasoning as spending.js's
// categoryColors, just keyed by type label instead of category.
const TYPE_COLOR_SLOTS = 12;

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

// Set while the dialog is open, so a toggle click can re-fetch this same
// month/kind and re-render in place without closing the dialog.
let currentTxDialogMonth = null;
let currentTxDialogKind = null;

function renderCashFlowByType(byType) {
  const section = document.getElementById("fin-cashflow-tx-breakdown-section");
  if (!section) return;
  if (!byType || byType.length === 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  const total = byType.reduce((sum, t) => sum + t.total, 0);
  const slices = byType.map((t, i) => ({
    label: `${t.type} (${t.count})`,
    value: t.total,
    colorVar: `--stock-${(i % TYPE_COLOR_SLOTS) + 1}`,
  }));
  renderLegend("fin-cashflow-tx-breakdown", slices, total);
}

function renderCashFlowTxRows(container, transactions) {
  container.innerHTML = "";
  if (transactions.length === 0) {
    container.innerHTML = `<p class="fin-empty-note">No transactions.</p>`;
    return;
  }
  for (const tx of transactions) {
    const row = document.createElement("div");
    row.className = "fin-category-tx-row fin-cashflow-tx-row";
    row.classList.toggle("fin-cashflow-tx-row-excluded", tx.excluded);
    row.innerHTML = `
      <span class="fin-category-tx-date">${formatShortDate(tx.date)}</span>
      <span class="fin-category-tx-description">${escapeHtml(tx.description)}</span>
      <span class="fin-category-tx-amount">${cad(tx.amount)}</span>
      <button type="button" class="fin-cashflow-tx-toggle" data-transaction-id="${escapeHtml(tx.id)}" data-excluded="${tx.excluded}">
        ${tx.excluded ? "Include" : "Exclude"}
      </button>
    `;
    container.appendChild(row);
  }

  container.querySelectorAll(".fin-cashflow-tx-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const transactionId = button.dataset.transactionId;
      const currentlyExcluded = button.dataset.excluded === "true";
      toggleCashFlowExclusion(transactionId, !currentlyExcluded);
    });
  });
}

async function toggleCashFlowExclusion(transactionId, excluded) {
  try {
    const res = await fetch("/finance/cash-flow-exclusions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transaction_id: transactionId, excluded }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.warn("finance cash flow: failed to update exclusion", err);
    return;
  }

  // The dialog stays open (unlike the category-edit dialog) so several rows
  // can be reviewed in one sitting - re-fetch this same month/kind in place,
  // then refresh the stat tiles/chart in the background so the numbers stay
  // correct without forcing the user back out of the dialog.
  if (currentTxDialogMonth) {
    await loadAndRenderCashFlowTx(currentTxDialogMonth, currentTxDialogKind);
  }
  const windowSelect = document.getElementById("fin-cashflow-window");
  if (windowSelect) renderCashFlow(windowSelect.value);
}

async function loadAndRenderCashFlowTx(month, kind) {
  const subtitle = document.getElementById("fin-cashflow-tx-dialog-subtitle");
  const list = document.getElementById("fin-cashflow-tx-list");
  try {
    const params = new URLSearchParams({ month, kind });
    const res = await fetch(`${CASH_FLOW_TX_URL}?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderCashFlowByType(data.byType);
    renderCashFlowTxRows(list, data.transactions);
    if (subtitle) {
      subtitle.textContent = `${data.transactions.length} transaction${data.transactions.length === 1 ? "" : "s"} · ${cad(data.total)}`;
    }
  } catch (err) {
    renderCashFlowByType([]);
    list.innerHTML = `<p class="fin-empty-note">Couldn't load transactions (${err.message}).</p>`;
  }
}

async function openCashFlowTransactions(month, kind) {
  const dialog = document.getElementById("fin-cashflow-tx-dialog");
  if (!dialog) return;

  currentTxDialogMonth = month;
  currentTxDialogKind = kind;

  const title = document.getElementById("fin-cashflow-tx-dialog-title");
  const subtitle = document.getElementById("fin-cashflow-tx-dialog-subtitle");
  const list = document.getElementById("fin-cashflow-tx-list");
  if (title) title.textContent = `${kind === "income" ? "Income" : "Expense"} — ${formatMonthTitle(month)}`;
  if (subtitle) subtitle.textContent = "";
  renderCashFlowByType([]);
  list.innerHTML = `<p class="fin-empty-note">Loading…</p>`;
  dialog.showModal();

  await loadAndRenderCashFlowTx(month, kind);
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

  const dialog = document.getElementById("fin-cashflow-tx-dialog");
  if (dialog) {
    dialog.addEventListener("close", () => {
      currentTxDialogMonth = null;
      currentTxDialogKind = null;
    });
  }
}
