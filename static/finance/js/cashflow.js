// Renders the "Cash Flow" section on /finance from
// GET /finance/cash-flow.json (finance/ARCHITECTURE.md Part A, Phase 4).
// Self-contained like ticker.js/import.js/spending.js - its own window
// selector, its own DOM, no dependency on spending.js beyond sharing
// charts.js's helpers.
import { drawIncomeExpenseChart } from "./charts.js";

const CASH_FLOW_URL = "/finance/cash-flow.json";

function cad(value, opts = {}) {
  return value.toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: opts.cents === false ? 0 : 2,
    maximumFractionDigits: opts.cents === false ? 0 : 2,
  });
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
  drawIncomeExpenseChart(canvas, tooltip, byMonth);
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
