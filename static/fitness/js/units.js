// Weight display-unit preference, shared between the dashboard card
// (components/weight-card.js) and the detail page (pages/weight.js).
// Values always travel over the wire in kg (see docs/api-contract.md) -
// this only affects how they're displayed, remembered per-browser via
// localStorage so the choice sticks across page loads.

const STORAGE_KEY = "personalHealth.weightUnit";
const KG_PER_LB = 0.45359237;

export function getWeightUnit() {
  return localStorage.getItem(STORAGE_KEY) === "lb" ? "lb" : "kg";
}

export function setWeightUnit(unit) {
  localStorage.setItem(STORAGE_KEY, unit);
}

export function convertFromKg(valueKg, unit) {
  return unit === "lb" ? valueKg / KG_PER_LB : valueKg;
}
