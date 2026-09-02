import { drawSparkline, formatShortDate } from "../charts.js";

// Shared dashboard-card renderer for metrics with a single {date, value}
// number per day (spo2, hrv, breathing_rate, temperature, weight). Unlike
// steps/heart_rate/sleep/activity, which each have a different response
// shape, all five of these follow the same api-contract.md shape, so one
// generic renderer covers them instead of five near-duplicate files.
export function renderSimpleValueCard(container, records, { unit = "", color = "#2563eb", decimals = 0 } = {}) {
  container.innerHTML = "";
  const latest = records[records.length - 1];

  const big = document.createElement("div");
  big.className = "card-metric";
  big.textContent = latest ? `${latest.value.toFixed(decimals)}${unit}` : "--";
  container.appendChild(big);

  const label = document.createElement("div");
  label.className = "card-sublabel";
  // See steps-card.js for why this says "in range" rather than just "on <date>".
  label.textContent = latest ? `Latest in range: ${formatShortDate(latest.date)}` : "no data in range";
  container.appendChild(label);

  const canvas = document.createElement("canvas");
  canvas.className = "sparkline";
  container.appendChild(canvas);
  drawSparkline(canvas, records.map((r) => r.value), {
    color,
    labels: records.map((r) => r.date),
  });
}
