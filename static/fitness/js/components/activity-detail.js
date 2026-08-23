import { buildActivityIcon } from "./activity-icons.js";
import { drawSparkline, drawStackedBar, formatTimeOfDay } from "../charts.js";
import { getMetricSamples } from "../api.js";

function formatType(type) {
  if (!type) return "Activity";
  return type
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatClock(isoStr) {
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return "--";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

const ZONES = [
  { key: "light", label: "Light", color: "#60a5fa" },
  { key: "moderate", label: "Moderate", color: "#3b82f6" },
  { key: "vigorous", label: "Vigorous", color: "#f97316" },
  { key: "peak", label: "Peak", color: "#dc2626" },
];

function addTile(grid, label, value) {
  if (value == null) return;
  const tile = document.createElement("div");
  tile.className = "activity-modal-tile";
  const v = document.createElement("div");
  v.className = "activity-modal-tile-value";
  v.textContent = value;
  const l = document.createElement("div");
  l.className = "activity-modal-tile-label";
  l.textContent = label;
  tile.appendChild(v);
  tile.appendChild(l);
  grid.appendChild(tile);
}

let dialog = null;

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.className = "activity-modal";
  // Clicking the backdrop (the ::backdrop-covered dialog element itself,
  // outside its content box) closes it - the standard native-<dialog>
  // click-outside-to-close pattern.
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close();
  });
  document.body.appendChild(dialog);
  return dialog;
}

// `exercise` is one entry from docs/api-contract.md's activity shape (now
// carrying start_time/end_time and the metricsSummary-derived fields - see
// backend/server.py's _reshape_activity), plus the `date` it fell on
// (stitched on by the caller, same as activity-card.js/pages/activity.js
// already do for their flattened lists).
export function openActivityDetail(exercise) {
  const dlg = ensureDialog();
  dlg.innerHTML = "";

  const closeBtn = document.createElement("button");
  closeBtn.className = "activity-modal-close";
  closeBtn.type = "button";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", () => dlg.close());
  dlg.appendChild(closeBtn);

  const header = document.createElement("div");
  header.className = "activity-modal-header";
  const type = document.createElement("span");
  type.className = "activity-type";
  type.appendChild(buildActivityIcon(exercise.type));
  type.appendChild(document.createTextNode(formatType(exercise.type)));
  header.appendChild(type);

  const when = document.createElement("div");
  when.className = "card-sublabel";
  const timeRange =
    exercise.start_time && exercise.end_time
      ? `${formatClock(exercise.start_time)} – ${formatClock(exercise.end_time)}`
      : null;
  when.textContent = [exercise.date, timeRange].filter(Boolean).join(" · ");
  header.appendChild(when);
  dlg.appendChild(header);

  const grid = document.createElement("div");
  grid.className = "activity-modal-summary";
  addTile(grid, "Duration", typeof exercise.duration_minutes === "number" ? `${exercise.duration_minutes} min` : null);
  addTile(grid, "Calories", typeof exercise.calories === "number" ? `${exercise.calories} cal` : null);
  addTile(
    grid,
    "Distance",
    typeof exercise.distance_meters === "number" && exercise.distance_meters > 0
      ? `${(exercise.distance_meters / 1000).toFixed(2)} km`
      : null
  );
  addTile(grid, "Steps", typeof exercise.steps === "number" ? exercise.steps.toLocaleString() : null);
  addTile(
    grid,
    "Avg pace",
    typeof exercise.average_pace_min_per_km === "number" && exercise.average_pace_min_per_km > 0
      ? `${exercise.average_pace_min_per_km.toFixed(1)} min/km`
      : null
  );
  addTile(grid, "Avg heart rate", typeof exercise.average_heart_rate === "number" ? `${exercise.average_heart_rate} bpm` : null);
  addTile(
    grid,
    "Active zone min",
    typeof exercise.active_zone_minutes === "number" ? `${exercise.active_zone_minutes}` : null
  );
  dlg.appendChild(grid);

  const zones = exercise.heart_rate_zones_minutes;
  const zoneTotal = zones ? ZONES.reduce((sum, z) => sum + (zones[z.key] || 0), 0) : 0;
  let zoneCanvas = null;
  if (zones && zoneTotal > 0) {
    const zoneSection = document.createElement("div");
    zoneSection.className = "activity-modal-section";
    const zoneTitle = document.createElement("h3");
    zoneTitle.textContent = "Heart rate zones";
    zoneSection.appendChild(zoneTitle);

    zoneCanvas = document.createElement("canvas");
    zoneCanvas.className = "stacked-bar";
    zoneSection.appendChild(zoneCanvas);

    const legend = document.createElement("div");
    legend.className = "stage-legend";
    for (const z of ZONES) {
      const item = document.createElement("span");
      item.className = "stage-legend-item";
      const swatch = document.createElement("i");
      swatch.style.backgroundColor = z.color;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(`${z.label} ${zones[z.key] || 0}m`));
      legend.appendChild(item);
    }
    zoneSection.appendChild(legend);
    dlg.appendChild(zoneSection);
  }

  const hrSection = document.createElement("div");
  hrSection.className = "activity-modal-section";
  const hrTitle = document.createElement("h3");
  hrTitle.textContent = "Heart rate during activity";
  hrSection.appendChild(hrTitle);
  const hrCanvas = document.createElement("canvas");
  hrCanvas.className = "sparkline activity-modal-chart";
  hrSection.appendChild(hrCanvas);
  const hrStatus = document.createElement("div");
  hrStatus.className = "card-sublabel";
  hrStatus.textContent = "loading…";
  hrSection.appendChild(hrStatus);
  dlg.appendChild(hrSection);

  // <dialog> content isn't laid out (clientWidth/Height are 0) until
  // showModal() runs, so every canvas draw - including the zone bar above -
  // has to happen after this, not while building the DOM.
  dlg.showModal();
  if (zoneCanvas) {
    drawStackedBar(zoneCanvas, ZONES.map((z) => ({ minutes: zones[z.key] || 0, color: z.color })));
  }

  if (!exercise.start_time || !exercise.end_time) {
    hrStatus.textContent = "no time window recorded for this activity";
    return;
  }

  getMetricSamples("heart_rate", exercise.start_time, exercise.end_time)
    .then((body) => {
      // The dialog may have been closed (or reopened for a different
      // activity) by the time this resolves - bail rather than draw into a
      // canvas that's no longer showing this exercise.
      if (!dlg.open || !dlg.contains(hrCanvas)) return;
      const samples = body.samples || [];
      if (samples.length === 0) {
        hrStatus.textContent = "no heart rate samples recorded during this activity";
        return;
      }
      hrStatus.textContent = "";
      drawSparkline(hrCanvas, samples.map((s) => s.value), {
        color: "#dc2626",
        labels: samples.map((s) => s.time),
        formatLabel: formatTimeOfDay,
      });
    })
    .catch((err) => {
      if (!dlg.open || !dlg.contains(hrCanvas)) return;
      hrStatus.textContent = `couldn't load heart rate: ${err.message}`;
    });
}
