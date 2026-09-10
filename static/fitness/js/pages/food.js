import { initMetricDetailPage } from "./metric-detail.js";
import { drawBarChart } from "../charts.js";

const FOOD_FIELDS = [
  ["Avg calories", "calories", " cal", 0],
  ["Avg carbs", "carbs_grams", " g", 1],
  ["Avg protein", "protein_grams", " g", 1],
  ["Avg fat", "fat_grams", " g", 1],
];

function formatAmount(value, unit, decimals) {
  return `${value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}${unit}`;
}

function average(records, key) {
  if (records.length === 0) return null;
  return records.reduce((sum, record) => sum + (record[key] || 0), 0) / records.length;
}

function renderChart(canvas, records) {
  drawBarChart(canvas, records.map((record) => record.calories), {
    colorVar: "--metric-food",
    labels: records.map((record) => record.date),
    yLabel: "Calories (cal)",
    accessibleLabel: "Calories logged per day",
  });
}

function renderTable(tbody, records) {
  tbody.innerHTML = "";
  for (const record of [...records].reverse()) {
    const row = document.createElement("tr");
    const values = [
      record.date,
      formatAmount(record.calories, " cal", 0),
      formatAmount(record.carbs_grams, " g", 1),
      formatAmount(record.protein_grams, " g", 1),
      formatAmount(record.fat_grams, " g", 1),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }
    tbody.appendChild(row);
  }
}

function renderStats(container, records) {
  container.innerHTML = "";
  if (records.length === 0) {
    const empty = document.createElement("p");
    empty.className = "stats-empty";
    empty.textContent = "No nutrition logs for this range.";
    container.appendChild(empty);
    return;
  }

  const rows = [
    ["Logged days", records.length.toLocaleString()],
    ...FOOD_FIELDS.map(([label, key, unit, decimals]) => [
      label,
      formatAmount(average(records, key), unit, decimals),
    ]),
  ];
  const list = document.createElement("dl");
  list.className = "stats-list";
  for (const [label, value] of rows) {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    list.append(term, detail);
  }
  container.appendChild(list);
}

initMetricDetailPage("food", {
  title: "Food",
  renderChart,
  renderTable,
  renderStats,
});
