// Chooses the dashboard card grid's column count so rows come out balanced
// (issue #32): every row has the same count when the card count divides
// evenly, otherwise the last row is short by exactly one card - never more.
// Recomputed against the grid's own box width (not just window resize),
// since that width also changes when the activity sidebar drops below the
// grid at css/styles.css's 700px breakpoint.

const CARD_MIN_WIDTH = 240; // matches css/styles.css's .dashboard-grid minmax()

function readGapPx(el) {
  const gap = parseFloat(getComputedStyle(el).columnGap);
  return Number.isNaN(gap) ? 0 : gap;
}

function maxColumnsFor(containerWidth, gap) {
  return Math.max(1, Math.floor((containerWidth + gap) / (CARD_MIN_WIDTH + gap)));
}

// Largest column count (up to `maxColumns`) whose last row is short by at
// most one card: a remainder of 0 (rows all equal) or `columns - 1` (last
// row one short of a full row). Falls back to a single column if nothing
// wider satisfies that.
function bestBalancedColumns(cardCount, maxColumns) {
  for (let columns = Math.min(maxColumns, cardCount); columns >= 1; columns--) {
    const remainder = cardCount % columns;
    if (remainder === 0 || remainder === columns - 1) return columns;
  }
  return 1;
}

export function initBalancedGrid(grid) {
  if (!grid) return;
  const cardCount = grid.children.length;
  if (cardCount === 0) return;

  function apply() {
    const maxColumns = maxColumnsFor(grid.clientWidth, readGapPx(grid));
    const columns = bestBalancedColumns(cardCount, maxColumns);
    grid.style.gridTemplateColumns = `repeat(${columns}, minmax(${CARD_MIN_WIDTH}px, 1fr))`;
  }

  apply();
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(apply).observe(grid);
  } else {
    window.addEventListener("resize", apply);
  }
}
