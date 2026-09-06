// Renders the "Spending" section on /finance from
// GET /finance/spending-summary.json (finance/ARCHITECTURE.md Part A5).
// Self-contained like ticker.js/import.js - fetches its own data and owns
// its own DOM, no change to dashboard.js's existing net-worth/cash/
// investment rendering beyond exporting the two row/legend helpers this
// reuses instead of duplicating their markup.
import { drawDonut, drawMonthlyBarChart } from "./charts.js";
import { renderRow, renderLegend } from "./dashboard.js";

const SUMMARY_URL = "/finance/spending-summary.json";
// Reuses dashboard.js's --stock-1..12 identity-color family (already a
// generic, validated 12-slot categorical palette, not something specific
// to stocks) rather than defining a second one for spending categories.
const CATEGORY_COLOR_SLOTS = 12;

function cad(value, opts = {}) {
  return value.toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: opts.cents === false ? 0 : 2,
    maximumFractionDigits: opts.cents === false ? 0 : 2,
  });
}

// Alphabetical assignment, not by current rank, so a category keeps the
// same identity color across window changes even as its rank shifts -
// same "color follows the entity, never rank" reasoning as
// dashboard.js's buildSymbolColors.
function categoryColors(byCategory) {
  const categories = [...new Set(byCategory.map((c) => c.category))].sort();
  if (categories.length > CATEGORY_COLOR_SLOTS) {
    console.warn(
      `finance spending: ${categories.length} categories exceeds the ${CATEGORY_COLOR_SLOTS} color slots - some will share an identity color.`
    );
  }
  const colors = new Map();
  categories.forEach((cat, i) => colors.set(cat, `--stock-${(i % CATEGORY_COLOR_SLOTS) + 1}`));
  return colors;
}

function renderCategoryDonut(byCategory) {
  const donutEl = document.getElementById("fin-spending-donut");
  const legendEl = document.getElementById("fin-spending-legend");
  const centerEl = document.getElementById("fin-spending-donut-center-value");
  if (!donutEl) return;

  const total = byCategory.reduce((sum, c) => sum + c.total, 0);
  if (centerEl) centerEl.textContent = cad(total, { cents: false });

  if (byCategory.length === 0) {
    donutEl.innerHTML = "";
    if (legendEl) legendEl.innerHTML = `<p class="fin-empty-note">No spending in this window yet.</p>`;
    return;
  }

  const colors = categoryColors(byCategory);
  const slices = byCategory.map((c) => ({ label: c.category, value: c.total, colorVar: colors.get(c.category) }));
  drawDonut(donutEl, slices, { label: "Spending by category" });
  renderLegend("fin-spending-legend", slices, total);
}

function renderTopMerchants(topMerchants) {
  const container = document.getElementById("fin-spending-merchants");
  if (!container) return;
  container.innerHTML = "";

  if (topMerchants.length === 0) {
    container.innerHTML = `<p class="fin-empty-note">No purchases in this window yet.</p>`;
    return;
  }

  const maxTotal = Math.max(...topMerchants.map((m) => m.total));
  for (const merchant of topMerchants) {
    renderRow(container, {
      label: merchant.merchant,
      value: merchant.total,
      total: maxTotal,
      colorVar: "--status-blue",
      meta: `${merchant.count} visit${merchant.count === 1 ? "" : "s"}`,
    });
  }
}

function renderMonthlyChart(byMonth) {
  const canvas = document.getElementById("fin-spend-month-canvas");
  const tooltip = document.getElementById("fin-spend-month-tooltip");
  const empty = document.getElementById("fin-spend-month-empty");
  if (!canvas) return;

  if (byMonth.length === 0) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  canvas.hidden = false;
  if (empty) empty.hidden = true;
  drawMonthlyBarChart(canvas, tooltip, byMonth, { colorVar: "--status-blue" });
}

async function loadSummary(window_) {
  const res = await fetch(`${SUMMARY_URL}?window=${encodeURIComponent(window_)}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function renderSpending(window_) {
  let data;
  try {
    data = await loadSummary(window_);
  } catch (err) {
    console.warn("finance spending: failed to load summary", err);
    return;
  }
  renderCategoryDonut(data.byCategory);
  renderTopMerchants(data.topMerchants);
  renderMonthlyChart(data.byMonth);
}

export function initFinanceSpending() {
  const select = document.getElementById("fin-spending-window");
  if (!select) return;
  renderSpending(select.value);
  select.addEventListener("change", () => renderSpending(select.value));
}
