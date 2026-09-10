// Rolling-window + distribution statistics for a metric detail page's
// sidebar (see issue #39): 7/14/30-day trailing averages, the
// week-over-week change, and the average, median, standard deviation,
// min, and max over whatever range is currently loaded.

export function average(values) {
  if (values.length === 0) return null;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

export function median(values) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

// Population standard deviation (divides by n, not n-1) - these are the
// full set of loaded samples for the range, not a sample drawn from a
// larger population.
export function standardDeviation(values) {
  if (values.length === 0) return null;
  const mean = average(values);
  return Math.sqrt(average(values.map((v) => (v - mean) ** 2)));
}

function addDays(dateStr, delta) {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + delta);
  return d.toISOString().slice(0, 10);
}

/**
 * `dateFor`/`valueFor` extract the date string and numeric value from each
 * record - records are shaped differently per metric (see pages/*.js).
 * Trailing windows are relative to the latest date present in `records`
 * rather than today, so a narrowed date-range selection still produces
 * sensible windows instead of always looking past the loaded data.
 */
export function computeMetricStats(records, { dateFor = (r) => r.date, valueFor = (r) => r.value } = {}) {
  const points = records
    .map((r) => ({ date: dateFor(r), value: valueFor(r) }))
    .filter((p) => typeof p.value === "number" && !Number.isNaN(p.value));

  if (points.length === 0) return null;

  const latestDate = points.reduce((max, p) => (p.date > max ? p.date : max), points[0].date);

  // `offsetDays` shifts the window's end back in time, so windowAverage(7)
  // is the latest 7 days and windowAverage(7, 7) is the 7 days before that
  // - used for the week-over-week comparison below.
  function windowAverage(days, offsetDays = 0) {
    const end = addDays(latestDate, -offsetDays);
    const cutoff = addDays(end, -(days - 1));
    const values = points.filter((p) => p.date >= cutoff && p.date <= end).map((p) => p.value);
    return average(values);
  }

  const allValues = points.map((p) => p.value);
  const week = windowAverage(7);
  const priorWeek = windowAverage(7, 7);

  return {
    week,
    twoWeek: windowAverage(14),
    month: windowAverage(30),
    weekDelta: week != null && priorWeek != null ? week - priorWeek : null,
    average: average(allValues),
    median: median(allValues),
    stdDev: standardDeviation(allValues),
    min: Math.min(...allValues),
    max: Math.max(...allValues),
  };
}
