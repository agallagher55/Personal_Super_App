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

// BTC quantities here are always small (a round-up buys thousandths of a
// cent's worth) - up to 8 decimal places (satoshi precision), trimmed of
// trailing zeros, never a $-style fixed count of decimals.
function formatBtc(value, { maximumFractionDigits = 8 } = {}) {
  return `${value.toLocaleString("en-CA", { maximumFractionDigits })} BTC`;
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
  const ctx = canvas.getContext("2d");

  let lineColor, gridColor, mutedColor, surfaceColor;
  function readThemeColors() {
    lineColor = themeColor("--ink");
    gridColor = themeColor("--line");
    mutedColor = themeColor("--ink-soft");
    surfaceColor = themeColor("--paper-raised");
  }
  readThemeColors();

  const padding = { top: 14, right: 10, bottom: 22, left: 60 };

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || Math.max(max, 1) * 0.1;
  const steps = 4;
  const { min: yMin, max: yMax, step: tickStep } = niceAxis(min - range * 0.15, max + range * 0.15, steps);
  const yRange = yMax - yMin || 1;
  const tickCount = Math.round(yRange / tickStep);

  // Rebuilt by measure() on every render - initial draw, a theme toggle,
  // and a resize (#81/#82) - so the backing store and the xFor/yFor scale
  // (and therefore the hover mapping) always match the canvas's current
  // on-screen size rather than whatever size it had at first draw.
  let cssWidth, cssHeight, innerH, xFor, yFor;

  function measure() {
    const dpr = window.devicePixelRatio || 1;
    cssWidth = canvas.clientWidth || canvas.width;
    cssHeight = canvas.clientHeight || canvas.height;
    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const innerW = cssWidth - padding.left - padding.right;
    innerH = cssHeight - padding.top - padding.bottom;
    xFor = (i) => padding.left + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
    yFor = (v) => padding.top + innerH - ((v - yMin) / yRange) * innerH;
  }

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

  function render() {
    measure();
    drawFrame(null);
  }

  render();

  // The colors above are read once and baked into the canvas bitmap, so a
  // light/dark toggle (data-theme flips on <html>, see static/js/theme.js)
  // needs an explicit redraw - nothing else invalidates the canvas.
  const themeObserver = new MutationObserver(() => {
    readThemeColors();
    render();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // The canvas's CSS size tracks its container (.fin-networth-canvas is
  // width: 100%) but the backing store and the xFor/yFor scale above were
  // only ever computed once - without this, a viewport resize squeezes the
  // stale bitmap (distorting the line/text) and leaves the hover crosshair
  // resolving against the old width. Debounced since resize fires rapidly.
  let resizeTimer = null;
  const resizeObserver = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 100);
  });
  resizeObserver.observe(canvas);

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
 * render as a visible sliver). Generic across all six dashboard donuts
 * (asset allocation, investment breakdown, portfolio by stock/ETF, and the
 * per-account holdings donuts) - only the slices and `label` differ.
 * `label` is this chart's accessible name (aria-label) - every call site
 * must pass one distinct to that chart, since screen readers otherwise
 * can't tell the donuts apart. `onSliceClick(slice)`, if given, makes
 * every segment clickable (pointer cursor + a click listener) - used by
 * static/finance/js/spending.js's click-a-category-to-filter-merchants
 * interaction; every other call site simply omits it and gets today's
 * hover-only behavior unchanged.
 */
export function drawDonut(container, slices, { label, onSliceClick }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  const radius = 54;
  const thickness = 22;
  const circumference = 2 * Math.PI * radius;
  const gap = total > 0 ? 2 : 0; // surface gap between segments

  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 140 140");
  svg.setAttribute("class", "donut-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", label);

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
    seg.dataset.label = slice.label;

    const title = document.createElementNS(svgNS, "title");
    const pct = (slice.value / total) * 100;
    title.textContent = `${slice.label}: ${formatCad(slice.value)} (${pct.toFixed(1)}%)`;
    seg.appendChild(title);

    if (onSliceClick) {
      seg.style.cursor = "pointer";
      seg.addEventListener("click", () => onSliceClick(slice));
    }

    svg.appendChild(seg);
    offset += length;
  }

  container.innerHTML = "";
  container.appendChild(svg);
}

/**
 * Draws a month-by-month stacked bar chart (e.g. spend per month broken
 * down by source, see static/finance/js/spending.js) on `canvas`, with
 * the same hover crosshair/tooltip convention as drawNetWorthChart above
 * - reuses that function's axis/resize/theme-redraw scaffolding, just
 * stacked bars instead of a line. `points` is
 * [{ month: "YYYY-MM", bySource: { [seriesKey]: number, ... } }, ...];
 * `series` is [{ key, colorVar }, ...] in bottom-to-top stacking order -
 * a month missing a given key (that source had no spend that month)
 * contributes a zero-height segment, not a gap. A single-entry `series`
 * degenerates to a plain single-colour bar per month. `onBarClick(month)`,
 * if given, makes every bar clickable (pointer cursor + a click listener) -
 * same convention as drawIncomeExpenseChart's onBarClick below, but this
 * chart's bars stack multiple sources rather than sitting side by side, so
 * a click resolves to the whole month rather than one segment - used by
 * static/finance/js/spending.js's click-a-bar-to-see-its-transactions
 * interaction.
 */
export function drawMonthlyBarChart(canvas, tooltipEl, points, series, { onBarClick } = {}) {
  const ctx = canvas.getContext("2d");

  let colors, gridColor, mutedColor;
  function readThemeColors() {
    colors = series.map((s) => themeColor(s.colorVar));
    gridColor = themeColor("--line");
    mutedColor = themeColor("--ink-soft");
  }
  readThemeColors();

  const padding = { top: 14, right: 10, bottom: 22, left: 60 };

  const totals = points.map((p) => series.reduce((sum, s) => sum + (p.bySource[s.key] || 0), 0));
  const maxVal = Math.max(...totals, 0);
  const { max: yMax, step: tickStep } = niceAxis(0, maxVal || 1, 4);
  const yRange = yMax || 1;
  const tickCount = Math.round(yMax / tickStep);

  let cssWidth, cssHeight, innerH, barWidth, xFor, yFor;

  function measure() {
    const dpr = window.devicePixelRatio || 1;
    cssWidth = canvas.clientWidth || canvas.width;
    cssHeight = canvas.clientHeight || canvas.height;
    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const innerW = cssWidth - padding.left - padding.right;
    innerH = cssHeight - padding.top - padding.bottom;
    const slot = points.length > 0 ? innerW / points.length : innerW;
    barWidth = Math.max(slot * 0.55, 4);
    xFor = (i) => padding.left + slot * i + slot / 2;
    yFor = (v) => padding.top + innerH - (v / yRange) * innerH;
  }

  function drawFrame(hoverIndex) {
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.fillStyle = mutedColor;
    ctx.font = "10px 'JetBrains Mono', monospace";
    for (let s = 0; s <= tickCount; s++) {
      const v = s * tickStep;
      const y = yFor(v);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(cssWidth - padding.right, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(formatCad(v), padding.left - 8, y);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    points.forEach((p, i) => {
      ctx.fillText(formatMonth(p.month), xFor(i), cssHeight - 6);
    });

    points.forEach((p, i) => {
      const x = xFor(i);
      ctx.globalAlpha = hoverIndex == null || i === hoverIndex ? 1 : 0.7;
      let cumulative = 0;
      series.forEach((s, si) => {
        const value = p.bySource[s.key] || 0;
        if (value <= 0) return;
        const yBottom = yFor(cumulative);
        const yTop = yFor(cumulative + value);
        ctx.fillStyle = colors[si];
        ctx.fillRect(x - barWidth / 2, yTop, barWidth, yBottom - yTop);
        cumulative += value;
      });
      ctx.globalAlpha = 1;
    });
  }

  function render() {
    measure();
    drawFrame(null);
  }

  render();

  const themeObserver = new MutationObserver(() => {
    readThemeColors();
    render();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  let resizeTimer = null;
  const resizeObserver = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 100);
  });
  resizeObserver.observe(canvas);

  if (onBarClick) {
    canvas.style.cursor = "pointer";
    canvas.addEventListener("click", (e) => {
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
      onBarClick(points[nearest].month);
    });
  }

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
    const total = series.reduce((sum, s) => sum + (p.bySource[s.key] || 0), 0);
    const breakdown = series
      .filter((s) => (p.bySource[s.key] || 0) > 0)
      .map((s) => `${s.key} ${formatCad(p.bySource[s.key])}`)
      .join(" · ");
    tooltipEl.textContent = breakdown
      ? `${formatMonth(p.month)} ${year} — ${formatCad(total)} (${breakdown})`
      : `${formatMonth(p.month)} ${year} — ${formatCad(total)}`;
    tooltipEl.style.left = `${xFor(nearest)}px`;
    tooltipEl.style.top = `${yFor(total)}px`;
    tooltipEl.classList.add("show");
  });

  canvas.addEventListener("mouseleave", () => {
    drawFrame(null);
    tooltipEl.classList.remove("show");
  });
}

/**
 * Draws a grouped income-vs-expense bar chart (two bars per month, both
 * rising from a shared zero baseline - income and expense are always
 * non-negative here, so a diverging up/down layout isn't needed) on
 * `canvas`, reusing the same axis/theme/resize/hover scaffolding as
 * drawMonthlyBarChart above. `points` is
 * [{ month: "YYYY-MM", income: number, expense: number }, ...].
 * `onBarClick(month, kind)`, if given, makes every bar clickable (pointer
 * cursor + a click listener - `kind` is "income" or "expense" depending on
 * which of the pair was clicked) - used by static/finance/js/cashflow.js's
 * click-a-bar-to-see-its-transactions interaction.
 */
export function drawIncomeExpenseChart(canvas, tooltipEl, points, { incomeColorVar = "--status-green", expenseColorVar = "--status-red", onBarClick } = {}) {
  const ctx = canvas.getContext("2d");

  let incomeColor, expenseColor, gridColor, mutedColor;
  function readThemeColors() {
    incomeColor = themeColor(incomeColorVar);
    expenseColor = themeColor(expenseColorVar);
    gridColor = themeColor("--line");
    mutedColor = themeColor("--ink-soft");
  }
  readThemeColors();

  const padding = { top: 14, right: 10, bottom: 22, left: 60 };

  const maxVal = Math.max(...points.flatMap((p) => [p.income, p.expense]), 0);
  const { max: yMax, step: tickStep } = niceAxis(0, maxVal || 1, 4);
  const yRange = yMax || 1;
  const tickCount = Math.round(yMax / tickStep);

  let cssWidth, cssHeight, innerH, barWidth, gap, xForGroup, yFor;

  function measure() {
    const dpr = window.devicePixelRatio || 1;
    cssWidth = canvas.clientWidth || canvas.width;
    cssHeight = canvas.clientHeight || canvas.height;
    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const innerW = cssWidth - padding.left - padding.right;
    innerH = cssHeight - padding.top - padding.bottom;
    const slot = points.length > 0 ? innerW / points.length : innerW;
    barWidth = Math.max(slot * 0.28, 3);
    gap = barWidth * 0.25;
    xForGroup = (i) => padding.left + slot * i + slot / 2;
    yFor = (v) => padding.top + innerH - (v / yRange) * innerH;
  }

  function drawFrame(hoverIndex) {
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.fillStyle = mutedColor;
    ctx.font = "10px 'JetBrains Mono', monospace";
    for (let s = 0; s <= tickCount; s++) {
      const v = s * tickStep;
      const y = yFor(v);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(cssWidth - padding.right, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(formatCad(v), padding.left - 8, y);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    points.forEach((p, i) => {
      ctx.fillText(formatMonth(p.month), xForGroup(i), cssHeight - 6);
    });

    points.forEach((p, i) => {
      const cx = xForGroup(i);
      ctx.globalAlpha = hoverIndex == null || i === hoverIndex ? 1 : 0.7;

      const incomeTop = yFor(p.income);
      ctx.fillStyle = incomeColor;
      ctx.fillRect(cx - barWidth - gap / 2, incomeTop, barWidth, padding.top + innerH - incomeTop);

      const expenseTop = yFor(p.expense);
      ctx.fillStyle = expenseColor;
      ctx.fillRect(cx + gap / 2, expenseTop, barWidth, padding.top + innerH - expenseTop);

      ctx.globalAlpha = 1;
    });
  }

  function render() {
    measure();
    drawFrame(null);
  }

  render();

  const themeObserver = new MutationObserver(() => {
    readThemeColors();
    render();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  let resizeTimer = null;
  const resizeObserver = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 100);
  });
  resizeObserver.observe(canvas);

  if (onBarClick) {
    canvas.style.cursor = "pointer";
    canvas.addEventListener("click", (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      let nearest = 0;
      let nearestDist = Infinity;
      points.forEach((_, i) => {
        const d = Math.abs(xForGroup(i) - mx);
        if (d < nearestDist) {
          nearestDist = d;
          nearest = i;
        }
      });
      // Which of the pair was clicked: left of center = income bar, right
      // of center = expense bar (matches the fillRect split in drawFrame).
      const kind = mx < xForGroup(nearest) ? "income" : "expense";
      onBarClick(points[nearest].month, kind);
    });
  }

  if (!tooltipEl) return;

  canvas.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    let nearest = 0;
    let nearestDist = Infinity;
    points.forEach((_, i) => {
      const d = Math.abs(xForGroup(i) - mx);
      if (d < nearestDist) {
        nearestDist = d;
        nearest = i;
      }
    });
    drawFrame(nearest);
    const p = points[nearest];
    const year = p.month.slice(0, 4);
    tooltipEl.textContent = `${formatMonth(p.month)} ${year} — ${formatCad(p.income)} in, ${formatCad(p.expense)} out`;
    tooltipEl.style.left = `${xForGroup(nearest)}px`;
    tooltipEl.style.top = `${yFor(Math.max(p.income, p.expense))}px`;
    tooltipEl.classList.add("show");
  });

  canvas.addEventListener("mouseleave", () => {
    drawFrame(null);
    tooltipEl.classList.remove("show");
  });
}

/**
 * Draws a month-by-month bar chart of BTC accumulated via Shakepay's
 * round-up-your-purchase feature (see static/finance/js/spending.js),
 * on `canvas` - same measure/render/hover/theme scaffolding as
 * drawMonthlyBarChart, but a single BTC-quantity series (not stacked by
 * source - a round-up's BTC value has one source by construction) with
 * BTC-formatted axis/tooltip text instead of currency. `points` is
 * [{ month: "YYYY-MM", btcQuantity: number }, ...]. Defaults to `--flag`,
 * the same color the asset-allocation donut already uses for "Bitcoin".
 */
export function drawBtcMonthlyChart(canvas, tooltipEl, points, { colorVar = "--flag" } = {}) {
  const ctx = canvas.getContext("2d");

  let barColor, gridColor, mutedColor;
  function readThemeColors() {
    barColor = themeColor(colorVar);
    gridColor = themeColor("--line");
    mutedColor = themeColor("--ink-soft");
  }
  readThemeColors();

  const padding = { top: 14, right: 10, bottom: 22, left: 76 };

  const values = points.map((p) => p.btcQuantity);
  const maxVal = Math.max(...values, 0);
  const { max: yMax, step: tickStep } = niceAxis(0, maxVal || 1e-8, 4);
  const yRange = yMax || 1;
  const tickCount = Math.round(yMax / tickStep);

  let cssWidth, cssHeight, innerH, barWidth, xFor, yFor;

  function measure() {
    const dpr = window.devicePixelRatio || 1;
    cssWidth = canvas.clientWidth || canvas.width;
    cssHeight = canvas.clientHeight || canvas.height;
    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const innerW = cssWidth - padding.left - padding.right;
    innerH = cssHeight - padding.top - padding.bottom;
    const slot = points.length > 0 ? innerW / points.length : innerW;
    barWidth = Math.max(slot * 0.55, 4);
    xFor = (i) => padding.left + slot * i + slot / 2;
    yFor = (v) => padding.top + innerH - (v / yRange) * innerH;
  }

  function drawFrame(hoverIndex) {
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.fillStyle = mutedColor;
    ctx.font = "10px 'JetBrains Mono', monospace";
    for (let s = 0; s <= tickCount; s++) {
      const v = s * tickStep;
      const y = yFor(v);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(cssWidth - padding.right, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(formatBtc(v, { maximumFractionDigits: 6 }), padding.left - 8, y);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    points.forEach((p, i) => {
      ctx.fillText(formatMonth(p.month), xFor(i), cssHeight - 6);
    });

    points.forEach((p, i) => {
      const x = xFor(i);
      const yTop = yFor(p.btcQuantity);
      ctx.globalAlpha = hoverIndex == null || i === hoverIndex ? 1 : 0.7;
      ctx.fillStyle = barColor;
      ctx.fillRect(x - barWidth / 2, yTop, barWidth, padding.top + innerH - yTop);
      ctx.globalAlpha = 1;
    });
  }

  function render() {
    measure();
    drawFrame(null);
  }

  render();

  const themeObserver = new MutationObserver(() => {
    readThemeColors();
    render();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  let resizeTimer = null;
  const resizeObserver = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 100);
  });
  resizeObserver.observe(canvas);

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
    tooltipEl.textContent = `${formatMonth(p.month)} ${year} — ${formatBtc(p.btcQuantity)}`;
    tooltipEl.style.left = `${xFor(nearest)}px`;
    tooltipEl.style.top = `${yFor(p.btcQuantity)}px`;
    tooltipEl.classList.add("show");
  });

  canvas.addEventListener("mouseleave", () => {
    drawFrame(null);
    tooltipEl.classList.remove("show");
  });
}
