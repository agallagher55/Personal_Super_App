import { initMetricDetailPage } from "./metric-detail.js";
import { drawSparkline } from "../charts.js";
import { computeMetricStats } from "../stats.js";
import { renderStatsPanel } from "../components/stats-panel.js";

// Shared detail-page wiring for the five {date, value}-shaped metrics
// (spo2, hrv, breathing_rate, temperature, weight) - see
// components/simple-value-card.js for why one generic implementation
// covers all five instead of five near-duplicate page scripts.
export function initSimpleValueDetailPage(metric, { title, unit = "", color = "#2563eb", decimals = 0 } = {}) {
  function renderChart(canvas, records) {
    drawSparkline(canvas, records.map((r) => r.value), {
      color,
      labels: records.map((r) => r.date),
    });
  }

  function renderTable(tbody, records) {
    tbody.innerHTML = "";
    for (const r of [...records].reverse()) {
      const tr = document.createElement("tr");
      const date = document.createElement("td");
      date.textContent = r.date;
      const value = document.createElement("td");
      value.textContent = `${r.value.toFixed(decimals)}${unit}`;
      tr.append(date, value);
      tbody.appendChild(tr);
    }
  }

  function renderStats(container, records) {
    renderStatsPanel(container, computeMetricStats(records), {
      format: (v) => `${v.toFixed(decimals)}${unit}`,
    });
  }

  initMetricDetailPage(metric, { title, renderChart, renderTable, renderStats });
}
