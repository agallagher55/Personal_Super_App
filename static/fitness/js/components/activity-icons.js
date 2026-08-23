// Maps an exercise `type` (docs/api-contract.md's activity shape, which
// passes Google Health's exerciseType/displayName straight through - see
// backend/server.py) to a small SVG icon. Google's exercise type enum has
// ~100 values, so this matches by keyword into a handful of icon families
// rather than listing every one, falling back to a generic bolt icon.
const SVG_NS = "http://www.w3.org/2000/svg";

const FAMILIES = [
  {
    test: /RUN/,
    shapes: [
      { tag: "circle", attrs: { cx: 14.5, cy: 4.5, r: 1.8 } },
      { tag: "path", attrs: { d: "M10 9.5l3.5 2-1 4 3 5" } },
      { tag: "path", attrs: { d: "M7 13.5l4-2 2 1 3-1" } },
      { tag: "path", attrs: { d: "M9.5 21l3-4.5" } },
    ],
  },
  {
    test: /HIK/,
    shapes: [{ tag: "path", attrs: { d: "M3 20l6-14 4 8 3-5 5 11z" } }],
  },
  {
    test: /WALK/,
    shapes: [
      { tag: "ellipse", attrs: { cx: 10, cy: 15, rx: 2.8, ry: 4.6 } },
      { tag: "circle", attrs: { cx: 10.2, cy: 7.5, r: 1.7 } },
    ],
    fill: true,
  },
  {
    test: /BIK|CYCL/,
    shapes: [
      { tag: "circle", attrs: { cx: 6, cy: 17, r: 3 } },
      { tag: "circle", attrs: { cx: 18, cy: 17, r: 3 } },
      { tag: "path", attrs: { d: "M6 17l4-8h4l4 8" } },
      { tag: "path", attrs: { d: "M10 9l2-3h3" } },
      { tag: "path", attrs: { d: "M12 17l2-6" } },
    ],
  },
  {
    test: /SWIM/,
    shapes: [
      { tag: "path", attrs: { d: "M2 15.5c1.5-1.5 3-1.5 4.5 0s3 1.5 4.5 0 3-1.5 4.5 0 3 1.5 4.5 0" } },
      { tag: "path", attrs: { d: "M2 19.5c1.5-1.5 3-1.5 4.5 0s3 1.5 4.5 0 3-1.5 4.5 0 3 1.5 4.5 0" } },
    ],
  },
  {
    test: /STRENGTH|WEIGHT|WORKOUT|HIIT|CROSSFIT|CIRCUIT/,
    shapes: [
      { tag: "rect", attrs: { x: 2, y: 9, width: 3, height: 6, rx: 1 } },
      { tag: "rect", attrs: { x: 19, y: 9, width: 3, height: 6, rx: 1 } },
      { tag: "line", attrs: { x1: 5, y1: 12, x2: 9, y2: 12 } },
      { tag: "line", attrs: { x1: 15, y1: 12, x2: 19, y2: 12 } },
      { tag: "rect", attrs: { x: 9, y: 7, width: 6, height: 10, rx: 1 } },
    ],
  },
  {
    test: /YOGA|PILATES|STRETCH/,
    shapes: [
      { tag: "circle", attrs: { cx: 12, cy: 4.5, r: 1.8 } },
      { tag: "path", attrs: { d: "M8 20c0-2 1.5-3 2-5l2-3 2 3c.5 2 2 3 2 5" } },
      { tag: "path", attrs: { d: "M6 14c2-1 4-1 6-3 2 2 4 2 6 3" } },
    ],
  },
  {
    test: /SOCCER|FOOTBALL|BASKETBALL|BASEBALL|SOFTBALL|TENNIS|VOLLEYBALL|HOCKEY|RUGBY|CRICKET|GOLF/,
    shapes: [
      { tag: "circle", attrs: { cx: 12, cy: 12, r: 9 } },
      { tag: "polyline", attrs: { points: "12 6 12 10 9 13 10 17 14 17 15 13 12 10" } },
    ],
  },
];

const DEFAULT_SHAPES = [{ tag: "polygon", attrs: { points: "13 2 3 14 12 14 11 22 21 10 12 10 13 2" } }];

// Builds an <svg> element for the given exercise type via the DOM API
// (rather than innerHTML) since these icons are inserted into an already
// live, scrolling activity list, and DOM nodes are attached exactly once.
export function buildActivityIcon(type) {
  const normalized = (type || "").toUpperCase();
  const family = FAMILIES.find((f) => f.test.test(normalized));
  const shapes = family ? family.shapes : DEFAULT_SHAPES;
  const fill = family && family.fill;

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "activity-icon");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  if (fill) {
    svg.setAttribute("fill", "currentColor");
  } else {
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
  }

  for (const shape of shapes) {
    const el = document.createElementNS(SVG_NS, shape.tag);
    for (const [name, value] of Object.entries(shape.attrs)) {
      el.setAttribute(name, value);
    }
    svg.appendChild(el);
  }

  return svg;
}
