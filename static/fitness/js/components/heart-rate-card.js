import { drawSparkline, formatShortDate } from "../charts.js";

// `records` is docs/api-contract.md's heart_rate shape: [{ date, resting }].
// "resting" is currently a min-of-day-samples approximation on the backend
// side - see docs/backend-architecture.md.
export function renderHeartRate(container, records) {
  container.innerHTML = "";
  const latest = records[records.length - 1];

  const big = document.createElement("div");
  big.className = "card-metric";
  big.textContent = latest ? `${latest.resting} bpm` : "--";
  container.appendChild(big);

  const label = document.createElement("div");
  label.className = "card-sublabel";
  // See steps-card.js for why this says "in range" rather than just "on <date>".
  label.textContent = latest ? `Latest in range: ${formatShortDate(latest.date)}` : "no data in range";
  container.appendChild(label);

  const canvas = document.createElement("canvas");
  canvas.className = "sparkline";
  container.appendChild(canvas);
  drawSparkline(canvas, records.map((r) => r.resting), {
    color: "#dc2626",
    labels: records.map((r) => r.date),
  });
}
