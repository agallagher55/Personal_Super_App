// Chooses the densest readable dashboard grid. Recomputed against the grid's
// own box width (not just window resize), since that width also changes when
// the activity sidebar drops below the grid at css/styles.css's breakpoint.
// Filling the available columns is more useful here than balancing the final
// row because it lets the full dashboard fit on a desktop screen.

const CARD_MIN_WIDTH = 220; // matches css/styles.css's .dashboard-grid minmax()

function readGapPx(el) {
  const gap = parseFloat(getComputedStyle(el).columnGap);
  return Number.isNaN(gap) ? 0 : gap;
}

function maxColumnsFor(containerWidth, gap) {
  return Math.max(1, Math.floor((containerWidth + gap) / (CARD_MIN_WIDTH + gap)));
}

export function initBalancedGrid(grid) {
  if (!grid) return;
  const cardCount = grid.children.length;
  if (cardCount === 0) return;

  function apply() {
    const maxColumns = maxColumnsFor(grid.clientWidth, readGapPx(grid));
    const columns = Math.min(cardCount, maxColumns);
    grid.style.gridTemplateColumns = `repeat(${columns}, minmax(${CARD_MIN_WIDTH}px, 1fr))`;
  }

  apply();
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(apply).observe(grid);
  } else {
    window.addEventListener("resize", apply);
  }
}
