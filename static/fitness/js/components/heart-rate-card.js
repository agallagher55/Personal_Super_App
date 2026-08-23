import { drawSparkline } from "../charts.js";

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
  label.textContent = latest ? `on ${latest.date}` : "no data in range";
  container.appendChild(label);

  const canvas = document.createElement("canvas");
  canvas.className = "sparkline";
  container.appendChild(canvas);
  drawSparkline(canvas, records.map((r) => r.resting), {
    color: "#dc2626",
    labels: records.map((r) => r.date),
  });
}
