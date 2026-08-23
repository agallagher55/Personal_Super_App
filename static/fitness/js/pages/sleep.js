import { initMetricDetailPage } from "./metric-detail.js";
import { drawSparkline } from "../charts.js";
import { computeMetricStats } from "../stats.js";
import { renderStatsPanel } from "../components/stats-panel.js";

function renderChart(canvas, records) {
  drawSparkline(canvas, records.map((r) => r.duration_minutes), {
    color: "#7c3aed",
    labels: records.map((r) => r.date),
  });
}

function formatDuration(minutes) {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${m}m`;
}

function renderTable(tbody, records) {
  tbody.innerHTML = "";
  for (const r of [...records].reverse()) {
    const tr = document.createElement("tr");
    const cells = [
      r.date,
      formatDuration(r.duration_minutes),
      `${r.stages.deep}m`,
      `${r.stages.rem}m`,
      `${r.stages.light}m`,
      `${r.stages.awake}m`,
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderStats(container, records) {
  const stats = computeMetricStats(records, { valueFor: (r) => r.duration_minutes });
  renderStatsPanel(container, stats, { format: formatDuration });
}

initMetricDetailPage("sleep", { title: "Sleep", renderChart, renderTable, renderStats });
