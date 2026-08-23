import { drawSparkline } from "../charts.js";
import { getWeightUnit, setWeightUnit, convertFromKg } from "../units.js";

const COLOR = "#4338ca";

// Dashboard weight card - like the other simple {date, value} metrics
// (see components/simple-value-card.js) but with its own kg/lbs toggle,
// which none of the other metrics need.
export function renderWeightCard(container, records) {
  let unit = getWeightUnit();

  function draw() {
    container.innerHTML = "";

    const toggle = document.createElement("div");
    toggle.className = "unit-toggle";
    for (const u of ["kg", "lb"]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = u;
      btn.className = u === unit ? "active" : "";
      btn.addEventListener("click", () => {
        if (unit === u) return;
        unit = u;
        setWeightUnit(unit);
        draw();
      });
      toggle.appendChild(btn);
    }
    container.appendChild(toggle);

    const latest = records[records.length - 1];
    const big = document.createElement("div");
    big.className = "card-metric";
    big.textContent = latest ? `${convertFromKg(latest.value, unit).toFixed(1)} ${unit}` : "--";
    container.appendChild(big);

    const label = document.createElement("div");
    label.className = "card-sublabel";
    label.textContent = latest ? `on ${latest.date}` : "no data in range";
    container.appendChild(label);

    const canvas = document.createElement("canvas");
    canvas.className = "sparkline";
    container.appendChild(canvas);
    drawSparkline(canvas, records.map((r) => convertFromKg(r.value, unit)), {
      color: COLOR,
      labels: records.map((r) => r.date),
    });
  }

  draw();
}
