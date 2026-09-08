import { drawStackedBar, formatShortDate } from "../charts.js";

// Deep/REM/Light are three lightness steps of the Sleep card's own violet
// and Awake is the odd one out in a warm hue - see the --sleep-* tokens in
// css/styles.css for why.
const STAGES = [
  { key: "deep", label: "Deep", colorVar: "--sleep-deep" },
  { key: "rem", label: "REM", colorVar: "--sleep-rem" },
  { key: "light", label: "Light", colorVar: "--sleep-light" },
  { key: "awake", label: "Awake", colorVar: "--sleep-awake" },
];

function formatDuration(minutes) {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${m}m`;
}

// `records` is fitness/API-CONTRACT.md's sleep shape:
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
    STAGES.map((s) => ({ minutes: latest.stages[s.key] || 0, colorVar: s.colorVar }))
  );

  const legend = document.createElement("div");
  legend.className = "stage-legend";
  for (const stage of STAGES) {
    const item = document.createElement("span");
    item.className = "stage-legend-item";

    const swatch = document.createElement("i");
    swatch.style.backgroundColor = `var(${stage.colorVar})`;
    item.appendChild(swatch);

    item.appendChild(document.createTextNode(`${stage.label} ${latest.stages[stage.key] || 0}m`));
    legend.appendChild(item);
  }
  container.appendChild(legend);
}
