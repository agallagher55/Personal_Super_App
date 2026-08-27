// Small dependency-free chart helpers for the /finance dashboard, drawn on
// <canvas>/inline SVG - same no-charting-library convention as
// static/fitness/js/charts.js. Colors are read from this page's CSS custom
// properties at draw time (rather than hardcoded hex) so both charts follow
// the current light/dark theme automatically.

const svgNS = "http://www.w3.org/2000/svg";

function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function formatCad(value, { maximumFractionDigits = 0 } = {}) {
  return value.toLocaleString("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits });
}

function formatMonth(monthStr) {
  const d = new Date(`${monthStr}-01T00:00:00`);
  if (Number.isNaN(d.getTime())) return monthStr;
  return d.toLocaleDateString(undefined, { month: "short" });
}

// Rounds `value` to a "nice" 1/2/5 x 10^n number (Heckbert's well-known
// "nice numbers for graph labels" algorithm) - `round` picks the nearest
// such number, while !round rounds up, which is what a nice *step size*
// needs so it never undershoots the requested tick count.
function niceNumber(value, round) {
  const exponent = Math.floor(Math.log10(value));
  const fraction = value / 10 ** exponent;
  let niceFraction;
  if (round) {
    if (fraction < 1.5) niceFraction = 1;
    else if (fraction < 3) niceFraction = 2;
    else if (fraction < 7) niceFraction = 5;
    else niceFraction = 10;
  } else {
    if (fraction <= 1) niceFraction = 1;
    else if (fraction <= 2) niceFraction = 2;
    else if (fraction <= 5) niceFraction = 5;
    else niceFraction = 10;
  }
  return niceFraction * 10 ** exponent;
}

// Rounds the [min, max] axis domain outward to nice round tick values
// (e.g. $32,207-$46,015 -> $32,000-$48,000 in steps of $4,000) instead of
// evenly dividing the raw range, which produces an arbitrary-looking tick
// on every gridline. targetSteps is a target, not a guarantee - the actual
// tick count comes out close to it but can vary by one either way.
function niceAxis(min, max, targetSteps) {
  const rawStep = (max - min) / targetSteps;
  const step = niceNumber(rawStep, true);
  return { min: Math.floor(min / step) * step, max: Math.ceil(max / step) * step, step };
}

/**
 * Draws a net-worth-over-time line chart on `canvas` and wires up a hover
 * crosshair + tooltip (per the dataviz skill: line/area charts ship hover by
 * default). `points` is [{ month: "YYYY-MM", value: number }, ...].
 * `tooltipEl` is an absolutely-positioned element inside the same
 * offsetParent as the canvas; pass null to skip hover wiring entirely.
 */
export function drawNetWorthChart(canvas, tooltipEl, points) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth || canvas.width;
  const cssHeight = canvas.clientHeight || canvas.height;
  canvas.width = cssWidth * dpr;
  canvas.height = cssHeight * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const lineColor = themeColor("--ink");
  const gridColor = themeColor("--line");
  const mutedColor = themeColor("--ink-soft");
  const surfaceColor = themeColor("--paper-raised");

  const padding = { top: 14, right: 10, bottom: 22, left: 60 };
  const innerW = cssWidth - padding.left - padding.right;
  const innerH = cssHeight - padding.top - padding.bottom;

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || Math.max(max, 1) * 0.1;
  const steps = 4;
  const { min: yMin, max: yMax, step: tickStep } = niceAxis(min - range * 0.15, max + range * 0.15, steps);
  const yRange = yMax - yMin || 1;
  const tickCount = Math.round(yRange / tickStep);

  const xFor = (i) => padding.left + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const yFor = (v) => padding.top + innerH - ((v - yMin) / yRange) * innerH;

  function drawFrame(hoverIndex) {
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    // Gridlines - hairline, one-step-off-surface, with $ tick labels.
    // Nice round values (niceAxis above) rather than an even division of
    // the raw range, so ticks read like $32,000/$36,000/... instead of an
    // arbitrary-looking $32,207/$35,659/....
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.fillStyle = mutedColor;
    ctx.font = "10px 'JetBrains Mono', monospace";
    for (let s = 0; s <= tickCount; s++) {
      const v = yMin + s * tickStep;
      const y = yFor(v);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(cssWidth - padding.right, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(formatCad(v), padding.left - 8, y);
    }

    // Month labels: first, middle, last - never one per point.
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    const labelIdxs = points.length > 1 ? [0, Math.round((points.length - 1) / 2), points.length - 1] : [0];
    for (const i of labelIdxs) {
      ctx.fillText(formatMonth(points[i].month), xFor(i), cssHeight - 6);
    }

    // Area wash - the series hue at ~10% opacity, never a saturated block.
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = xFor(i);
      const y = yFor(p.value);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineTo(xFor(points.length - 1), padding.top + innerH);
    ctx.lineTo(xFor(0), padding.top + innerH);
    ctx.closePath();
    ctx.globalAlpha = 0.1;
    ctx.fillStyle = lineColor;
    ctx.fill();
    ctx.globalAlpha = 1;

    // The line itself - 2px, round join/cap.
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = xFor(i);
      const y = yFor(p.value);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    // End-dot on the most recent point, always shown.
    const lastI = points.length - 1;
    ctx.beginPath();
    ctx.arc(xFor(lastI), yFor(points[lastI].value), 4, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();

    if (hoverIndex != null && hoverIndex !== lastI) {
      const x = xFor(hoverIndex);
      ctx.beginPath();
      ctx.moveTo(x, padding.top);
      ctx.lineTo(x, padding.top + innerH);
      ctx.strokeStyle = gridColor;
      ctx.lineWidth = 1;
      ctx.stroke();

      const y = yFor(points[hoverIndex].value);
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = lineColor;
      ctx.fill();
      // Surface ring so the hover dot stays legible over the line/area.
      ctx.lineWidth = 2;
      ctx.strokeStyle = surfaceColor;
      ctx.stroke();
    }
  }

  drawFrame(null);
  if (!tooltipEl) return;

  canvas.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    let nearest = 0;
    let nearestDist = Infinity;
    points.forEach((_, i) => {
      const d = Math.abs(xFor(i) - mx);
      if (d < nearestDist) {
        nearestDist = d;
        nearest = i;
      }
    });
    drawFrame(nearest);
    const p = points[nearest];
    const year = p.month.slice(0, 4);
    tooltipEl.textContent = `${formatMonth(p.month)} ${year} — ${formatCad(p.value)}`;
    tooltipEl.style.left = `${xFor(nearest)}px`;
    tooltipEl.style.top = `${yFor(p.value)}px`;
    tooltipEl.classList.add("show");
  });

  canvas.addEventListener("mouseleave", () => {
    drawFrame(null);
    tooltipEl.classList.remove("show");
  });
}

/**
 * Renders a donut chart (a pie with the center left open for a headline
 * figure) into `container`. `slices` is
 * [{ label, value, colorVar: "--status-blue" }, ...]. Each segment carries
 * a native SVG <title> as its hover tooltip - segments are marks, per the
 * dataviz skill every mark needs one, and this needs no extra JS wiring.
 * Zero-value slices are skipped (a hairline dasharray gap would otherwise
 * render as a visible sliver). Generic across both dashboard donuts (asset
 * allocation, investment breakdown) - only the slices passed in differ.
 */
export function drawDonut(container, slices) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  const radius = 54;
  const thickness = 22;
  const circumference = 2 * Math.PI * radius;
  const gap = total > 0 ? 2 : 0; // surface gap between segments

  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 140 140");
  svg.setAttribute("class", "donut-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Asset allocation");

  const track = document.createElementNS(svgNS, "circle");
  track.setAttribute("cx", "70");
  track.setAttribute("cy", "70");
  track.setAttribute("r", String(radius));
  track.setAttribute("fill", "none");
  track.setAttribute("stroke", "var(--line)");
  track.setAttribute("stroke-width", String(thickness));
  svg.appendChild(track);

  let offset = 0;
  for (const slice of slices) {
    if (!(slice.value > 0)) continue;
    const length = (slice.value / total) * circumference;
    const seg = document.createElementNS(svgNS, "circle");
    seg.setAttribute("cx", "70");
    seg.setAttribute("cy", "70");
    seg.setAttribute("r", String(radius));
    seg.setAttribute("fill", "none");
    seg.setAttribute("stroke", `var(${slice.colorVar})`);
    seg.setAttribute("stroke-width", String(thickness));
    seg.setAttribute("stroke-dasharray", `${Math.max(length - gap, 0)} ${circumference - Math.max(length - gap, 0)}`);
    seg.setAttribute("stroke-dashoffset", String(-offset));
    seg.setAttribute("transform", "rotate(-90 70 70)");
    seg.classList.add("donut-seg");

    const title = document.createElementNS(svgNS, "title");
    const pct = (slice.value / total) * 100;
    title.textContent = `${slice.label}: ${formatCad(slice.value)} (${pct.toFixed(1)}%)`;
    seg.appendChild(title);

    svg.appendChild(seg);
    offset += length;
  }

  container.innerHTML = "";
  container.appendChild(svg);
}
