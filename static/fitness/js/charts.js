// Small dependency-free chart helpers, drawn on <canvas> (see
// docs/frontend-architecture.md - no charting library for v1).

const DPR = window.devicePixelRatio || 1;

function prepareCanvas(canvas) {
  const cssWidth = canvas.clientWidth || canvas.width;
  const cssHeight = canvas.clientHeight || canvas.height;
  canvas.width = cssWidth * DPR;
  canvas.height = cssHeight * DPR;
  const ctx = canvas.getContext("2d");
  ctx.scale(DPR, DPR);
  return { ctx, width: cssWidth, height: cssHeight };
}

const LABEL_COLOR = "#64748b"; // matches css/styles.css's --text-muted - labels
// are never drawn in the series color (see the dataviz skill: text wears
// text tokens, not the data color).
const LABEL_FONT = "10px system-ui, sans-serif";

function formatValue(v) {
  return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function formatShortDate(dateStr) {
  const d = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Alternate label formatter for drawSparkline's `formatLabel` option, for
// series whose labels are full ISO instants (e.g. heart_rate samples
// windowed to an activity, see components/activity-detail.js) rather than
// bare dates.
export function formatTimeOfDay(isoStr) {
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return isoStr;
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/**
 * Draws a simple line sparkline for `values` (an array of numbers; gaps can
 * be represented as null/undefined and are skipped, not interpolated).
 *
 * Labels selectively rather than on every point (see the dataviz skill -
 * "never a number on every point"): the min/max values (the extremes - the
 * point of a trend line) and the most recent value (what a reader looks for
 * first) when `labelExtremes` is set, plus the first/last x-axis labels -
 * and, where they fit without crowding, a few evenly-spaced labels in
 * between - when `labels` (e.g. each point's date) is provided. Value and
 * date labels each do their own collision check and quietly skip rather
 * than overlap (see marks-and-anatomy.md's "when end-labels collide, don't
 * stack them").
 */
export function drawSparkline(canvas, values, { color = "#3b82f6", padding = 4, labels = null, labelExtremes = true, formatLabel = formatShortDate } = {}) {
  const { ctx, width, height } = prepareCanvas(canvas);
  ctx.clearRect(0, 0, width, height);

  const points = values
    .map((v, i) => ({ i, v }))
    .filter((p) => typeof p.v === "number" && !Number.isNaN(p.v));

  if (points.length === 0) {
    ctx.fillStyle = LABEL_COLOR;
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("no data", width / 2, height / 2);
    return;
  }

  const hasDateLabels = Array.isArray(labels) && labels.length === values.length;
  const hasExtremeLabels = labelExtremes && points.length >= 1;
  // Value labels (extremes) and date labels get their own reserved rows so
  // they never land on the same baseline - a min point that happens to
  // fall on the first/last day (as `steps`' partial "today" count often
  // does) would otherwise draw its value directly on top of the date
  // label at that same edge. See the dataviz skill's guidance against
  // colliding direct labels.
  const bottomDatePad = hasDateLabels ? 12 : 0;
  const topValuePad = hasExtremeLabels ? 14 : 0;
  const bottomValuePad = hasExtremeLabels ? 14 : 0;

  const min = Math.min(...points.map((p) => p.v));
  const max = Math.max(...points.map((p) => p.v));
  const range = max - min || 1;
  const innerW = width - padding * 2;
  const innerH = height - padding * 2 - topValuePad - bottomValuePad - bottomDatePad;
  const n = values.length;

  const xFor = (i) => padding + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const yFor = (v) => padding + topValuePad + innerH - ((v - min) / range) * innerH;

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  let started = false;
  for (const p of points) {
    const x = xFor(p.i);
    const y = yFor(p.v);
    if (!started) {
      ctx.moveTo(x, y);
      started = true;
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();

  // Dot on the last real point.
  const last = points[points.length - 1];
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(xFor(last.i), yFor(last.v), 3, 0, Math.PI * 2);
  ctx.fill();

  function alignFor(x) {
    if (x < width * 0.15) return "left";
    if (x > width * 0.85) return "right";
    return "center";
  }

  if (labelExtremes) {
    ctx.fillStyle = LABEL_COLOR;
    ctx.font = LABEL_FONT;

    // Bounding-box collision check, kept separate per side of the line so a
    // "below" label never has to dodge an "above" one - only labels sharing
    // a side can actually overlap.
    const placed = { above: [], below: [] };
    const labelGap = 4;
    function place(point, side) {
      const text = formatValue(point.v);
      const x = xFor(point.i);
      const align = alignFor(x);
      const w = ctx.measureText(text).width;
      const left = align === "left" ? x : align === "right" ? x - w : x - w / 2;
      const right = left + w;
      if (placed[side].some((r) => left - labelGap < r.right && right + labelGap > r.left)) return;
      ctx.textAlign = align;
      ctx.fillText(text, x, side === "above" ? yFor(point.v) - 5 : yFor(point.v) + 11);
      placed[side].push({ left, right });
    }

    if (points.length > 1) {
      const maxPoint = points.reduce((a, b) => (b.v > a.v ? b : a));
      const minPoint = points.reduce((a, b) => (b.v < a.v ? b : a));
      place(maxPoint, "above");
      if (minPoint.i !== maxPoint.i) place(minPoint, "below");

      // The most recent value is the one a reader looks for first, so label
      // it too when it isn't already an extreme above - on whichever side
      // has more room around it, skipping quietly (via `place`'s collision
      // check) if it would still crowd an extreme label.
      const last = points[points.length - 1];
      if (last.i !== maxPoint.i && last.i !== minPoint.i) {
        const mid = (min + max) / 2;
        place(last, last.v >= mid ? "above" : "below");
      }
    } else {
      // A single point has no trend to speak of - label it directly rather
      // than leaving a bare dot with nothing but a duplicated date range.
      place(points[0], "above");
    }
  }

  if (hasDateLabels) {
    ctx.fillStyle = LABEL_COLOR;
    ctx.font = LABEL_FONT;
    const dateY = height - 2;
    const placed = [];
    const labelGap = 8;
    function place(index, align) {
      const text = formatLabel(labels[index]);
      const x = xFor(index);
      const w = ctx.measureText(text).width;
      const left = align === "left" ? x : align === "right" ? x - w : x - w / 2;
      const right = left + w;
      if (placed.some((r) => left - labelGap < r.right && right + labelGap > r.left)) return;
      ctx.textAlign = align;
      ctx.fillText(text, x, dateY);
      placed.push({ left, right });
    }

    if (labels[0] === labels[labels.length - 1]) {
      place(0, "center");
    } else {
      place(0, "left");
      place(n - 1, "right");
      // Fill in the otherwise-bare middle (most visible on the 30-day
      // detail view) wherever a tick fits without crowding its neighbors.
      for (const frac of [0.5, 0.25, 0.75]) {
        const index = Math.round(frac * (n - 1));
        if (index > 0 && index < n - 1) place(index, "center");
      }
    }
  }
}

/**
 * Draws a vertical bar chart for `values` (one bar per entry, baselined at
 * zero - unlike drawSparkline's zoomed-to-range trend line, a bar's height
 * is only a fair read of magnitude when it starts at zero). Gaps
 * (null/undefined) are skipped. Mirrors drawSparkline's label conventions:
 * the peak bar's value when `labelExtremes` is set, and the first/last
 * x-axis labels when `labels` (e.g. each bar's date) is provided.
 */
export function drawBarChart(canvas, values, { color = "#3b82f6", padding = 4, labels = null, labelExtremes = true } = {}) {
  const { ctx, width, height } = prepareCanvas(canvas);
  ctx.clearRect(0, 0, width, height);

  const points = values
    .map((v, i) => ({ i, v }))
    .filter((p) => typeof p.v === "number" && !Number.isNaN(p.v));

  if (points.length === 0) {
    ctx.fillStyle = LABEL_COLOR;
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("no data", width / 2, height / 2);
    return;
  }

  const hasDateLabels = Array.isArray(labels) && labels.length === values.length;
  const hasExtremeLabels = labelExtremes && points.length >= 1;
  const bottomDatePad = hasDateLabels ? 12 : 0;
  const topValuePad = hasExtremeLabels ? 14 : 0;

  const max = Math.max(...points.map((p) => p.v)) || 1;
  const innerW = width - padding * 2;
  const innerH = height - padding * 2 - topValuePad - bottomDatePad;
  const n = values.length;

  const slot = innerW / n;
  const barWidth = Math.max(1, slot - 2);
  const xFor = (i) => padding + i * slot + (slot - barWidth) / 2;
  const yFor = (v) => padding + topValuePad + innerH - (v / max) * innerH;
  const baseline = padding + topValuePad + innerH;

  ctx.fillStyle = color;
  for (const p of points) {
    const x = xFor(p.i);
    const y = yFor(p.v);
    ctx.fillRect(x, y, barWidth, baseline - y);
  }

  function alignFor(x) {
    if (x < width * 0.15) return "left";
    if (x > width * 0.85) return "right";
    return "center";
  }

  if (hasExtremeLabels) {
    const maxPoint = points.reduce((a, b) => (b.v > a.v ? b : a));
    const labelX = xFor(maxPoint.i) + barWidth / 2;
    ctx.fillStyle = LABEL_COLOR;
    ctx.font = LABEL_FONT;
    ctx.textAlign = alignFor(labelX);
    ctx.fillText(formatValue(maxPoint.v), labelX, yFor(maxPoint.v) - 5);
  }

  if (hasDateLabels) {
    ctx.fillStyle = LABEL_COLOR;
    ctx.font = LABEL_FONT;
    if (labels[0] === labels[labels.length - 1]) {
      ctx.textAlign = "center";
      ctx.fillText(formatShortDate(labels[0]), width / 2, height - 2);
    } else {
      ctx.textAlign = "left";
      ctx.fillText(formatShortDate(labels[0]), padding, height - 2);
      ctx.textAlign = "right";
      ctx.fillText(formatShortDate(labels[labels.length - 1]), width - padding, height - 2);
    }
  }
}

/**
 * Draws a horizontal stacked bar for sleep stages: segments is an array of
 * { minutes, color }, drawn left-to-right in the order given.
 */
export function drawStackedBar(canvas, segments, { padding = 2 } = {}) {
  const { ctx, width, height } = prepareCanvas(canvas);
  ctx.clearRect(0, 0, width, height);

  const total = segments.reduce((sum, s) => sum + (s.minutes || 0), 0);
  const innerW = width - padding * 2;
  const barHeight = height - padding * 2;

  if (total <= 0) {
    ctx.fillStyle = "#e2e8f0";
    ctx.fillRect(padding, padding, innerW, barHeight);
    return;
  }

  let x = padding;
  for (const seg of segments) {
    const segWidth = (Math.max(seg.minutes, 0) / total) * innerW;
    if (segWidth <= 0) continue;
    ctx.fillStyle = seg.color;
    ctx.fillRect(x, padding, segWidth, barHeight);
    x += segWidth;
  }
}
