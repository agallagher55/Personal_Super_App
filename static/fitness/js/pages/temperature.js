import { initSimpleValueDetailPage } from "./simple-value-metric.js";

// "temperature" is nightly skin-temperature variation from a personal
// baseline (see google_health_client.py's DATA_TYPES, issue #30), not an
// absolute body temperature reading - values are deviations and can be
// negative.
initSimpleValueDetailPage("temperature", { title: "Temperature Variation", unit: "°C", color: "#ea580c", decimals: 2 });
