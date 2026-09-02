import { drawBarChart, formatShortDate } from "../charts.js";

// `records` is docs/api-contract.md's steps shape: [{ date, value }].
export function renderSteps(container, records) {
  container.innerHTML = "";
  const latest = records[records.length - 1];

  const big = document.createElement("div");
  big.className = "card-metric";
  big.textContent = latest ? latest.value.toLocaleString() : "--";
  container.appendChild(big);

  const label = document.createElement("div");
  label.className = "card-sublabel";
  // Says "in range" explicitly rather than just "on <date>" - this is the
  // most recent day within whatever range the header's filter requested,
  // not necessarily today, and that wasn't obvious when the two happened
  // to coincide (the common case, since most ranges end today).
  label.textContent = latest ? `Latest in range: ${formatShortDate(latest.date)}` : "no data in range";
  container.appendChild(label);

  const canvas = document.createElement("canvas");
  canvas.className = "sparkline";
  container.appendChild(canvas);
  drawBarChart(canvas, records.map((r) => r.value), {
    color: "#2563eb",
    labels: records.map((r) => r.date),
  });
}
