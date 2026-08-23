import { initMetricDetailPage } from "./metric-detail.js";
import { drawSparkline } from "../charts.js";
import { getWeightUnit, setWeightUnit, convertFromKg } from "../units.js";
import { computeMetricStats } from "../stats.js";
import { renderStatsPanel } from "../components/stats-panel.js";

const COLOR = "#4338ca";

let unit = getWeightUnit();
let records = [];
let chartCanvas = null;
let tableBody = null;
let statsContainer = null;

function draw() {
  if (chartCanvas) {
    drawSparkline(chartCanvas, records.map((r) => convertFromKg(r.value, unit)), {
      color: COLOR,
      labels: records.map((r) => r.date),
    });
  }
  if (tableBody) {
    tableBody.innerHTML = "";
    for (const r of [...records].reverse()) {
      const tr = document.createElement("tr");
      const date = document.createElement("td");
      date.textContent = r.date;
      const value = document.createElement("td");
      value.textContent = `${convertFromKg(r.value, unit).toFixed(1)} ${unit}`;
      tr.append(date, value);
      tableBody.appendChild(tr);
    }
  }
  if (statsContainer) {
    // Recomputed in the display unit (not kg) so the kg/lb toggle updates
    // the sidebar the same way it updates the chart and table.
    const stats = computeMetricStats(records, { valueFor: (r) => convertFromKg(r.value, unit) });
    renderStatsPanel(statsContainer, stats, { format: (v) => `${v.toFixed(1)} ${unit}` });
  }
  for (const btn of document.querySelectorAll("#unit-toggle button")) {
    btn.classList.toggle("active", btn.dataset.unit === unit);
  }
}

function renderChart(canvas, newRecords) {
  chartCanvas = canvas;
  records = newRecords;
  draw();
}

function renderTable(tbody, newRecords) {
  tableBody = tbody;
  records = newRecords;
  draw();
}

function renderStats(container, newRecords) {
  statsContainer = container;
  records = newRecords;
  draw();
}

for (const btn of document.querySelectorAll("#unit-toggle button")) {
  btn.addEventListener("click", () => {
    const newUnit = btn.dataset.unit;
    if (newUnit === unit) return;
    unit = newUnit;
    setWeightUnit(unit);
    draw();
  });
}

initMetricDetailPage("weight", { title: "Weight", renderChart, renderTable, renderStats });
