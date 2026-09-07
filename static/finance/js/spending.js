// Renders the "Spending" section on /finance from
// GET /finance/spending-summary.json (finance/ARCHITECTURE.md Part A5),
// including the "Editing categories" one-time/permanent fix dialog.
// Self-contained like ticker.js/import.js - fetches its own data and owns
// its own DOM, no change to dashboard.js's existing net-worth/cash/
// investment rendering beyond exporting the row/legend/escape helpers this
// reuses instead of duplicating their markup.
import { drawDonut, drawMonthlyBarChart, drawBtcMonthlyChart } from "./charts.js";
import { renderLegend, escapeHtml } from "./dashboard.js";

const SUMMARY_URL = "/finance/spending-summary.json";
const MERCHANT_TX_URL = "/finance/merchant-transactions.json";
const SET_TRANSACTION_CATEGORY_URL = "/finance/categories/transaction";
const SET_MERCHANT_CATEGORY_URL = "/finance/categories/merchant";
const BTC_BY_MONTH_URL = "/finance/shakepay-btc-by-month.json";
// Reuses dashboard.js's --stock-1..12 identity-color family (already a
// generic, validated 12-slot categorical palette, not something specific
// to stocks) rather than defining a second one for spending categories.
const CATEGORY_COLOR_SLOTS = 12;

// Which window is currently selected, and which category (if any) the
// Top Merchants list is drilled down to - reset to no category whenever
// the window changes, so switching time ranges never leaves a stale
// filter pointing at data outside the new window.
let currentWindow = "month";
let selectedCategory = null;

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

// Same alphabetical-assignment convention as categoryColors above, over
// every source that appears in any month (not just the most recent one),
// so a source's color stays the same across the whole chart even if it
// only shows up in some months.
function sourceColors(byMonthBySource) {
  const sources = [...new Set(byMonthBySource.flatMap((m) => Object.keys(m.bySource)))].sort();
  if (sources.length > CATEGORY_COLOR_SLOTS) {
    console.warn(
      `finance spending: ${sources.length} sources exceeds the ${CATEGORY_COLOR_SLOTS} color slots - some will share an identity color.`
    );
  }
  const colors = new Map();
  sources.forEach((source, i) => colors.set(source, `--stock-${(i % CATEGORY_COLOR_SLOTS) + 1}`));
  return colors;
}

// Clicking a category (donut segment or legend row) filters Top Merchants
// down to it; clicking the same category again clears the filter. Only
// the merchants list is re-fetched - byCategory/byMonth don't depend on
// the category filter, so the donut/legend stay showing the whole
// picture and only get restyled (selected/dimmed), not rebuilt.
function handleCategoryClick(slice) {
  selectedCategory = selectedCategory === slice.label ? null : slice.label;
  applySelectionHighlight();
  loadAndRenderMerchants();
}

function applySelectionHighlight() {
  document.querySelectorAll("#fin-spending-legend .fin-legend-row").forEach((row) => {
    const isSelected = !!selectedCategory && row.dataset.label === selectedCategory;
    row.classList.toggle("fin-legend-row-selected", isSelected);
    row.classList.toggle("fin-legend-row-dimmed", !!selectedCategory && !isSelected);
  });
  document.querySelectorAll("#fin-spending-donut .donut-seg").forEach((seg) => {
    const isSelected = !!selectedCategory && seg.dataset.label === selectedCategory;
    seg.classList.toggle("donut-seg-selected", isSelected);
    seg.classList.toggle("donut-seg-dimmed", !!selectedCategory && !isSelected);
  });

  const filterBar = document.getElementById("fin-merchants-filter");
  const filterLabel = document.getElementById("fin-filter-chip-label");
  if (filterBar) filterBar.hidden = !selectedCategory;
  if (filterLabel) filterLabel.textContent = selectedCategory || "";
}

function populateCategoryOptions(byCategory) {
  const datalist = document.getElementById("fin-category-options");
  if (!datalist) return;
  datalist.innerHTML = byCategory.map((c) => `<option value="${escapeHtml(c.category)}"></option>`).join("");
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
  drawDonut(donutEl, slices, { label: "Spending by category", onSliceClick: handleCategoryClick });
  renderLegend("fin-spending-legend", slices, total, { onClick: handleCategoryClick });
  applySelectionHighlight();
}

// Top Merchants rows are built directly here rather than through
// dashboard.js's shared renderRow(), since these need an "edit category"
// button the other renderRow callers (Cash, Debt, Investments, LOC) have
// no use for - keeps that shared helper generic.
function renderTopMerchants(topMerchants) {
  const container = document.getElementById("fin-spending-merchants");
  if (!container) return;
  container.innerHTML = "";

  if (topMerchants.length === 0) {
    const message = selectedCategory ? `No purchases in "${selectedCategory}" for this window.` : "No purchases in this window yet.";
    container.innerHTML = `<p class="fin-empty-note">${message}</p>`;
    return;
  }

  const maxTotal = Math.max(...topMerchants.map((m) => m.total));
  for (const merchant of topMerchants) {
    const pct = maxTotal > 0 ? (merchant.total / maxTotal) * 100 : 0;
    const row = document.createElement("div");
    row.className = "fin-row";
    row.innerHTML = `
      <div class="fin-row-top">
        <span class="fin-row-label">${escapeHtml(merchant.merchant)}
          <button class="fin-edit-category-btn" type="button" aria-label="Edit category for ${escapeHtml(merchant.merchant)}">&#9998;</button>
        </span>
        <span class="fin-row-value">${cad(merchant.total)}</span>
      </div>
      <div class="fin-row-bar-track">
        <div class="fin-row-bar-fill" style="width:${pct.toFixed(1)}%; background:var(--status-blue)"></div>
      </div>
      <div class="fin-row-pct">${merchant.count} visit${merchant.count === 1 ? "" : "s"}</div>
    `;
    row.querySelector(".fin-edit-category-btn").addEventListener("click", () => openCategoryEditor(merchant.merchant));
    container.appendChild(row);
  }
}

// `byMonthBySource` is [{ month, bySource: { sourceLabel: amount } }, ...]
// (summary.monthly_trend_by_source) - each source (e.g. "Wealthsimple",
// "Shakepay") gets its own color, stacked into one bar per month, with a
// legend below naming which color is which source.
function renderMonthlyChart(byMonthBySource) {
  const canvas = document.getElementById("fin-spend-month-canvas");
  const tooltip = document.getElementById("fin-spend-month-tooltip");
  const empty = document.getElementById("fin-spend-month-empty");
  const legendEl = document.getElementById("fin-spend-month-legend");
  if (!canvas) return;

  if (byMonthBySource.length === 0) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    if (legendEl) legendEl.innerHTML = "";
    return;
  }
  canvas.hidden = false;
  if (empty) empty.hidden = true;

  const colors = sourceColors(byMonthBySource);
  const series = [...colors.keys()].map((key) => ({ key, colorVar: colors.get(key) }));
  drawMonthlyBarChart(canvas, tooltip, byMonthBySource, series);

  if (legendEl) {
    const totals = new Map();
    for (const month of byMonthBySource) {
      for (const [source, amount] of Object.entries(month.bySource)) {
        totals.set(source, (totals.get(source) || 0) + amount);
      }
    }
    const grandTotal = [...totals.values()].reduce((sum, v) => sum + v, 0);
    const slices = series.map((s) => ({ label: s.key, value: totals.get(s.key) || 0, colorVar: s.colorVar }));
    renderLegend("fin-spend-month-legend", slices, grandTotal, { compact: true });
  }
}

async function loadSummary(window_, category) {
  const params = new URLSearchParams({ window: window_ });
  if (category) params.set("category", category);
  const res = await fetch(`${SUMMARY_URL}?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Not window-scoped (always the full history, like Spend by Month's own
// byMonth/byMonthBySource) so this loads once at page load rather than
// re-fetching on every This month/30 days/... change.
async function renderBtcAccumulated() {
  const canvas = document.getElementById("fin-btc-month-canvas");
  const tooltip = document.getElementById("fin-btc-month-tooltip");
  const empty = document.getElementById("fin-btc-month-empty");
  if (!canvas) return;

  let byMonth;
  try {
    const res = await fetch(BTC_BY_MONTH_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    ({ byMonth } = await res.json());
  } catch (err) {
    console.warn("finance spending: failed to load BTC accumulated by month", err);
    return;
  }

  if (byMonth.length === 0) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  canvas.hidden = false;
  if (empty) empty.hidden = true;
  drawBtcMonthlyChart(canvas, tooltip, byMonth);
}

async function loadAndRenderMerchants() {
  try {
    const data = await loadSummary(currentWindow, selectedCategory);
    renderTopMerchants(data.topMerchants);
  } catch (err) {
    console.warn("finance spending: failed to load filtered merchants", err);
  }
}

async function renderSpending(window_) {
  currentWindow = window_;
  selectedCategory = null;

  let data;
  try {
    data = await loadSummary(currentWindow, selectedCategory);
  } catch (err) {
    console.warn("finance spending: failed to load summary", err);
    return;
  }
  renderCategoryDonut(data.byCategory);
  renderTopMerchants(data.topMerchants);
  renderMonthlyChart(data.byMonthBySource);
  populateCategoryOptions(data.byCategory);
}

// --- Editing categories (one-time fix per transaction, permanent fix per
// merchant) - finance/ARCHITECTURE.md "Editing categories" ---------------

function setDialogStatus(message, isError) {
  const el = document.getElementById("fin-category-dialog-status");
  if (!el) return;
  el.hidden = !message;
  el.textContent = message || "";
  el.classList.toggle("fin-category-dialog-status-error", !!isError);
}

function renderTransactionEditRows(container, transactions) {
  container.innerHTML = "";
  if (transactions.length === 0) {
    container.innerHTML = `<p class="fin-empty-note">No individual transactions in this window.</p>`;
    return;
  }
  for (const tx of transactions) {
    const row = document.createElement("div");
    row.className = "fin-category-tx-row";
    row.innerHTML = `
      <span class="fin-category-tx-date">${formatShortDate(tx.date)}</span>
      <span class="fin-category-tx-amount">${cad(tx.amount)}</span>
      <input type="text" class="fin-category-tx-input" list="fin-category-options" value="${escapeHtml(tx.category || "")}">
      <button type="button" class="fin-category-tx-save">Save</button>
    `;
    row.querySelector(".fin-category-tx-save").addEventListener("click", () => {
      const input = row.querySelector(".fin-category-tx-input");
      saveTransactionCategory(tx.id, input.value.trim());
    });
    container.appendChild(row);
  }
}

async function openCategoryEditor(merchant) {
  const dialog = document.getElementById("fin-category-dialog");
  if (!dialog) return;

  dialog.dataset.merchant = merchant;
  document.getElementById("fin-category-dialog-merchant").textContent = merchant;
  document.getElementById("fin-category-dialog-permanent-input").value = "";
  setDialogStatus("", false);
  const txList = document.getElementById("fin-category-dialog-transactions");
  txList.innerHTML = `<p class="fin-empty-note">Loading…</p>`;
  dialog.showModal();

  try {
    const params = new URLSearchParams({ merchant, window: currentWindow });
    const res = await fetch(`${MERCHANT_TX_URL}?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderTransactionEditRows(txList, data.transactions);
  } catch (err) {
    txList.innerHTML = `<p class="fin-empty-note">Couldn't load transactions (${err.message}).</p>`;
  }
}

async function saveTransactionCategory(transactionId, category) {
  setDialogStatus("Saving…", false);
  try {
    const res = await fetch(SET_TRANSACTION_CATEGORY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transaction_id: transactionId, category }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || `HTTP ${res.status}`);
    document.getElementById("fin-category-dialog").close();
    renderSpending(currentWindow);
  } catch (err) {
    setDialogStatus(`Couldn't save: ${err.message}`, true);
  }
}

async function savePermanentCategory() {
  const dialog = document.getElementById("fin-category-dialog");
  const merchant = dialog?.dataset.merchant;
  const input = document.getElementById("fin-category-dialog-permanent-input");
  const category = input.value.trim();
  if (!merchant || !category) return;

  setDialogStatus("Saving…", false);
  try {
    const res = await fetch(SET_MERCHANT_CATEGORY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: merchant, category }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || `HTTP ${res.status}`);
    dialog.close();
    renderSpending(currentWindow);
  } catch (err) {
    setDialogStatus(`Couldn't save: ${err.message}`, true);
  }
}

export function initFinanceSpending() {
  const select = document.getElementById("fin-spending-window");
  if (!select) return;
  renderSpending(select.value);
  select.addEventListener("change", () => renderSpending(select.value));
  renderBtcAccumulated();

  const clearButton = document.getElementById("fin-merchants-filter-clear");
  if (clearButton) {
    clearButton.addEventListener("click", () => {
      selectedCategory = null;
      applySelectionHighlight();
      loadAndRenderMerchants();
    });
  }

  const permanentSaveButton = document.getElementById("fin-category-dialog-permanent-save");
  if (permanentSaveButton) permanentSaveButton.addEventListener("click", savePermanentCategory);
}
