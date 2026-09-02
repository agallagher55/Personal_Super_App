import { drawStackedBar, formatShortDate } from "../charts.js";

const STAGES = [
  { key: "deep", label: "Deep", color: "#1e3a8a" },
  { key: "rem", label: "REM", color: "#7c3aed" },
  { key: "light", label: "Light", color: "#60a5fa" },
  { key: "awake", label: "Awake", color: "#f97316" },
];

function formatDuration(minutes) {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${m}m`;
}

// `records` is docs/api-contract.md's sleep shape:
// [{ date, duration_minutes, stages: { light, deep, rem, awake } }].
export function renderSleep(container, records) {
  container.innerHTML = "";
  const latest = records[records.length - 1];

  if (!latest) {
    const empty = document.createElement("div");
    empty.className = "card-sublabel";
    empty.textContent = "no data in range";
    container.appendChild(empty);
    return;
  }

  const big = document.createElement("div");
  big.className = "card-metric";
  big.textContent = formatDuration(latest.duration_minutes);
  container.appendChild(big);

  const label = document.createElement("div");
  label.className = "card-sublabel";
  // See steps-card.js for why this says "in range" rather than just "night of <date>".
  label.textContent = `Latest in range: night of ${formatShortDate(latest.date)}`;
  container.appendChild(label);

  const canvas = document.createElement("canvas");
  canvas.className = "stacked-bar";
  container.appendChild(canvas);
  drawStackedBar(
    canvas,
    STAGES.map((s) => ({ minutes: latest.stages[s.key] || 0, color: s.color }))
  );

  const legend = document.createElement("div");
  legend.className = "stage-legend";
  for (const stage of STAGES) {
    const item = document.createElement("span");
    item.className = "stage-legend-item";

    const swatch = document.createElement("i");
    swatch.style.backgroundColor = stage.color;
    item.appendChild(swatch);

    item.appendChild(document.createTextNode(`${stage.label} ${latest.stages[stage.key] || 0}m`));
    legend.appendChild(item);
  }
  container.appendChild(legend);
}
