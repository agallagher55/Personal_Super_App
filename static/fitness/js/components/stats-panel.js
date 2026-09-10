// Renders the sidebar stats panel next to a detail page's chart (issue
// #39), from the stats object produced by js/stats.js's computeMetricStats.
export function renderStatsPanel(container, stats, { format = (v) => v.toFixed(1) } = {}) {
  if (!container) return;
  container.innerHTML = "";

  if (!stats) {
    const p = document.createElement("p");
    p.className = "stats-empty";
    p.textContent = "No data for this range.";
    container.appendChild(p);
    return;
  }

  // Signed magnitude (e.g. "+1.2 kg" / "-1.2 kg") rather than reusing
  // `format` directly - a plain average/median reads fine unsigned, but a
  // week-over-week change needs its direction front and center.
  function formatDelta(v) {
    const sign = v > 0 ? "+" : v < 0 ? "-" : "";
    return `${sign}${format(Math.abs(v))}`;
  }

  const rows = [
    ["7-day avg", stats.week, format],
    ["14-day avg", stats.twoWeek, format],
    ["30-day avg", stats.month, format],
    ["Wk vs. prior wk", stats.weekDelta, formatDelta],
    ["Average", stats.average, format],
    ["Median", stats.median, format],
    ["Std dev", stats.stdDev, format],
    ["Min", stats.min, format],
    ["Max", stats.max, format],
  ];

  const dl = document.createElement("dl");
  dl.className = "stats-list";
  for (const [label, value, formatValue] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value == null ? "--" : formatValue(value);
    dl.append(dt, dd);
  }
  container.appendChild(dl);
}
