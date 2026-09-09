import { formatShortDate } from "../charts.js";

function amount(value, unit) {
  return `${Math.round(value || 0).toLocaleString()}${unit}`;
}

export function renderFoodCard(container, records) {
  container.innerHTML = "";
  const latest = records[records.length - 1];

  const calories = document.createElement("div");
  calories.className = "card-metric";
  calories.textContent = latest ? amount(latest.calories, " cal") : "--";
  container.appendChild(calories);

  const label = document.createElement("div");
  label.className = "card-sublabel";
  label.textContent = latest ? `Latest logged day: ${formatShortDate(latest.date)}` : "no food data in range";
  container.appendChild(label);

  const macros = document.createElement("dl");
  macros.className = "food-macros";
  for (const [name, value] of [
    ["Carbs", latest?.carbs_grams],
    ["Protein", latest?.protein_grams],
    ["Fat", latest?.fat_grams],
  ]) {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = name;
    detail.textContent = latest ? amount(value, " g") : "--";
    item.append(term, detail);
    macros.appendChild(item);
  }
  container.appendChild(macros);
}
