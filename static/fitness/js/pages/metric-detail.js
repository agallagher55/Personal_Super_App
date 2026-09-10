import { getMetricDetail } from "../api.js";
import { renderPageHeader } from "../components/page-header.js";
import { loadLastSynced, wireSyncButton } from "../sync-control.js";

// Matches fitness/API-CONTRACT.md's per-metric detail default: last 30 days.
const RANGE_DAYS = 30;

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

function defaultRange() {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - (RANGE_DAYS - 1));
  return { from: isoDate(from), to: isoDate(to) };
}

/**
 * Wires up a per-metric detail page: header (title, date-range form, sync
 * button), status line, and metric-specific chart/table rendering supplied
 * by the caller. Mirrors dashboard.js's range/sync handling but against
 * GET /api/metrics/{metric} instead of the dashboard summary endpoint.
 */
export function initMetricDetailPage(metric, { title, renderChart, renderTable, renderStats }) {
  const header = renderPageHeader(document.getElementById("page-header"), {
    title,
    showSync: true,
  });

  const els = {
    form: header.form,
    from: header.from,
    to: header.to,
    sync: header.sync,
    lastSynced: header.lastSynced,
    status: document.getElementById("status"),
    chart: document.getElementById("chart"),
    tableBody: document.getElementById("table-body"),
    stats: document.getElementById("stats"),
  };

  // Keep the chart's identity in ordinary HTML rather than relying only on
  // text painted into the canvas. This remains visible at every canvas size
  // and gives the canvas a stable accessible name.
  const chartTitle = document.createElement("h2");
  chartTitle.className = "detail-chart-title";
  chartTitle.id = `${metric.replace(/_/g, "-")}-chart-title`;
  chartTitle.textContent = `${title} trend`;
  els.chart.before(chartTitle);
  els.chart.setAttribute("aria-labelledby", chartTitle.id);

  function setStatus(message, isError = false) {
    els.status.textContent = message;
    els.status.classList.toggle("status-error", isError);
    els.status.classList.toggle("status-busy", !isError && /^(Syncing|Loading)…$/.test(message));
  }

  function currentRange() {
    const fallback = defaultRange();
    return { from: els.from.value || fallback.from, to: els.to.value || fallback.to };
  }

  // Guards against out-of-order responses: the initial page-load fetch and
  // a filter applied before it resolves are two concurrent requests, and
  // network timing doesn't respect call order - see dashboard.js's
  // loadDashboard() for the same guard and the full explanation.
  let loadSequence = 0;

  async function load(from, to, { preserveStatus = false } = {}) {
    const requestId = ++loadSequence;
    if (!preserveStatus) setStatus("Loading…");
    try {
      const data = await getMetricDetail(metric, from, to);
      if (requestId !== loadSequence) return;
      renderChart(els.chart, data.records);
      renderTable(els.tableBody, data.records);
      if (renderStats) renderStats(els.stats, data.records);
      const count = data.records.length;
      if (!preserveStatus) {
        setStatus(`Showing ${data.from} to ${data.to} (${count} record${count === 1 ? "" : "s"})`);
      }
    } catch (err) {
      if (requestId !== loadSequence) return;
      setStatus(`Failed to load: ${err.message}`, true);
    }
  }

  els.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const { from, to } = currentRange();
    load(from, to);
  });

  wireSyncButton(els.sync, els.lastSynced, {
    setStatus,
    onDone: ({ result, error }) => {
      const { from, to } = currentRange();
      load(from, to, { preserveStatus: Boolean(result || error) });
    },
  });

  const initial = defaultRange();
  els.from.value = initial.from;
  els.to.value = initial.to;
  load(initial.from, initial.to);
  loadLastSynced(els.lastSynced);
}
