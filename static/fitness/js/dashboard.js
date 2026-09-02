import { getHealth, getMetrics, triggerSync } from "./api.js";
import { renderPageHeader } from "./components/page-header.js";
import { loadLastSynced, wireSyncButton } from "./sync-control.js";
import { initBalancedGrid } from "./balanced-grid.js";
import { renderSteps } from "./components/steps-card.js";
import { renderHeartRate } from "./components/heart-rate-card.js";
import { renderSleep } from "./components/sleep-card.js";
import { renderActivity } from "./components/activity-card.js";
import { renderSimpleValueCard } from "./components/simple-value-card.js";
import { renderWeightCard } from "./components/weight-card.js";

const header = renderPageHeader(document.getElementById("page-header"), {
  title: "Personal Health",
  showSync: true,
});

const els = {
  form: header.form,
  from: header.from,
  to: header.to,
  sync: header.sync,
  lastSynced: header.lastSynced,
  status: document.getElementById("status"),
  steps: document.getElementById("steps-card-body"),
  heartRate: document.getElementById("heart-rate-card-body"),
  sleep: document.getElementById("sleep-card-body"),
  activity: document.getElementById("activity-card-body"),
  spo2: document.getElementById("spo2-card-body"),
  hrv: document.getElementById("hrv-card-body"),
  breathingRate: document.getElementById("breathing-rate-card-body"),
  temperature: document.getElementById("temperature-card-body"),
  weight: document.getElementById("weight-card-body"),
};

// Matches the per-metric styling used on each metric's own detail page
// (js/pages/{spo2,hrv,breathing-rate,temperature}.js). `weight` is handled
// separately below via renderWeightCard, since it's the only one with a
// unit toggle (kg/lbs).
const SIMPLE_VALUE_METRICS = [
  { key: "spo2", el: "spo2", unit: "%", color: "#0891b2", decimals: 1 },
  { key: "hrv", el: "hrv", unit: " ms", color: "#9333ea", decimals: 1 },
  { key: "breathing_rate", el: "breathingRate", unit: " br/min", color: "#0d9488", decimals: 1 },
  { key: "temperature", el: "temperature", unit: "°C", color: "#ea580c", decimals: 2 },
];

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

// Matches docs/api-contract.md's dashboard default: last 7 days.
function defaultRange() {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 6);
  return { from: isoDate(from), to: isoDate(to) };
}

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.classList.toggle("status-error", isError);
  els.status.classList.toggle("status-busy", !isError && /^(Syncing|Loading)…$/.test(message));
}

function currentRange() {
  const fallback = defaultRange();
  return { from: els.from.value || fallback.from, to: els.to.value || fallback.to };
}

// A visitor who just signed in has an empty store, so every card would
// otherwise render "no data" with no explanation. Fires at most once per
// page load, and only when the store is genuinely untouched (rather than
// merely empty for the selected range).
let firstSyncAttempted = false;

async function maybeRunFirstSync() {
  if (firstSyncAttempted) return false;
  firstSyncAttempted = true;
  try {
    const health = await getHealth();
    if (health.data_store_last_modified !== null) return false;
  } catch (err) {
    return false;
  }
  setStatus("No data yet, pulling it from Google now…");
  try {
    await triggerSync();
    return true;
  } catch (err) {
    setStatus(`Failed to load: ${err.message}`, true);
    return false;
  }
}

async function loadDashboard(from, to) {
  setStatus("Loading…");
  try {
    const data = await getMetrics(from, to);
    const isEmpty = Object.values(data.metrics).every((records) => (records || []).length === 0);
    if (isEmpty && (await maybeRunFirstSync())) {
      return loadDashboard(from, to);
    }
    renderSteps(els.steps, data.metrics.steps);
    renderHeartRate(els.heartRate, data.metrics.heart_rate);
    renderSleep(els.sleep, data.metrics.sleep);
    renderActivity(els.activity, data.metrics.activity);
    for (const m of SIMPLE_VALUE_METRICS) {
      renderSimpleValueCard(els[m.el], data.metrics[m.key] || [], {
        unit: m.unit,
        color: m.color,
        decimals: m.decimals,
      });
    }
    renderWeightCard(els.weight, data.metrics.weight || []);
    setStatus(`Showing ${data.from} to ${data.to}`);
  } catch (err) {
    setStatus(`Failed to load: ${err.message}`, true);
  }
}

function init() {
  initBalancedGrid(document.querySelector(".dashboard-grid"));

  const initial = defaultRange();
  els.from.value = initial.from;
  els.to.value = initial.to;

  els.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const { from, to } = currentRange();
    loadDashboard(from, to);
  });

  wireSyncButton(els.sync, els.lastSynced, {
    setStatus,
    onDone: () => {
      const { from, to } = currentRange();
      loadDashboard(from, to);
    },
  });

  loadDashboard(initial.from, initial.to);
  loadLastSynced(els.lastSynced);
}

init();
