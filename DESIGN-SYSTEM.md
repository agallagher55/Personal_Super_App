# Design System

One visual language across every page of this app: `/`, `/tasks`,
`/fitness`, `/finance`, and the standalone `roadmap.html`. Plain CSS custom
properties, no framework, no build step.

Until 2026-09-08 that wasn't true: `/fitness` arrived as a port of the
standalone [`personal_health`](https://github.com/agallagher55/personal_health)
project and kept its own slate-and-blue Tailwind-ish palette, `system-ui`
type, filled cards, and a dark-mode toggle in the opposite corner, while
the rest of the app used the warm "sheet of paper" look. Both were themed,
so both had a dark mode — they just weren't the *same* dark mode. This
document is what they were unified onto.

## Where the tokens live

| File | Owns |
|---|---|
| `static/styles/styles.css` | **The palette.** `--paper`, `--ink`, `--line`, `--flag`, `--status-*`, the three font stacks, and both themes' values. Plus the page shell (`body`, `.page`, `.sheet`, `header`, `.back-link`, `.theme-toggle`) and everything the tasks pages need. Loaded first by every page. |
| `static/styles/nav.css` | The global nav bar only. Deliberately self-contained `--gnav-*` hex tokens (approximations of the palette above) so the bar renders identically even on a page that hasn't loaded `styles.css`. |
| `static/finance/css/dashboard.css` | `/finance` components, plus the `--stock-*` and `--invest-*` accent scales. |
| `static/finance/css/ticker.css` | The `/finance` watchlist sidebar. |
| `static/fitness/css/styles.css` | `/fitness` components, plus the `--metric-*` and `--sleep-*` accent scales. |
| `roadmap.html` | Its own copy of the palette, inline — see [Exceptions](#exceptions). |

A section stylesheet **adds accent scales and components**. It never
redefines `--paper`/`--ink`/`--line`/`--flag`/`--status-*`, and it is always
loaded *after* `styles.css` so its rules win where they overlap:

```html
<link rel="stylesheet" href="/static/styles/styles.css">
<link rel="stylesheet" href="/static/styles/nav.css">
<link rel="stylesheet" href="/static/fitness/css/styles.css">
```

## The palette

Colors are authored in `oklch()` — perceptually uniform, so "the same
color, one step lighter" is an honest lightness change rather than a
guess, which is what makes the light/dark pairs and the accent ramps below
tractable.

| Token | Role |
|---|---|
| `--paper` | Page background |
| `--paper-raised` | A sheet or panel sitting on the page |
| `--ink` | Body text, and the 2px rule under a page title |
| `--ink-soft` | Labels, metadata, axis text, anything secondary |
| `--line` | Borders, dividers, chart gridlines |
| `--flag` | The accent: links, primary buttons, focus rings, the active nav underline |
| `--flag-soft` | Tinted accent background |
| `--status-red` / `-yellow` / `-green` / `-blue` / `-grey` | Semantic state, and ordered ramps like heart rate zones |

Everything is warm (hue ~75) except the accent and status colors. Dark mode
flips lightness and lifts chroma slightly; it is the *same* identity in a
dark room, not a second palette.

## Type

| Token | Stack | Used for |
|---|---|---|
| `--serif` | Newsreader | Page titles and big numbers — **always italic**. This is the app's signature. |
| `--sans` | Work Sans | Body copy, card titles, buttons |
| `--mono` | JetBrains Mono | Labels, metadata, dates, amounts, table data, chart axes |

Uppercase mono at 10-12px with `letter-spacing` is the standard label
treatment (`.fin-stat-label`, `.card h2`, `.data-table th`, `.home-card-label`).

## Components

Recurring shapes, so a new section has something to copy rather than
invent:

- **Sheet** — `.sheet`: `--paper-raised`, 1px `--line`, 10px radius. The
  page's main surface. Sections that need more than the 800px default set
  their own width (`.page-finance`, `.page-fitness`, `.page-tasks`).
- **Card** — a bordered, *transparent* box on the sheet: 1px `--line`, 8px
  radius, ~18px/20px padding. `.fin-stat`, `.fin-overview-card`,
  `.home-card`, and `/fitness`'s `.card` are all this. Cards on a sheet
  don't get their own fill; only a panel beside the sheet does.
- **Sidebar panel** — `--paper-raised`, 1px `--line`, 10px radius, sticky.
  `/finance`'s watchlist (`.ticker-panel`) and `/fitness`'s Activity list
  (`.activity-panel .card`).
- **Big number** — `--serif`, italic, 26-28px, 600.
- **Secondary button** — mono 12px, `--ink-soft`, transparent, 1px
  `--line`, 6px radius; on hover `--ink` text and an `--ink-soft` border.
- **Primary button** — `--sans` 600 on `--flag`, `--paper-raised` text,
  100px pill radius; on hover the background goes `--ink`.
- **Dialog** — `--paper-raised`, 1px `--line`, 10px radius,
  `rgba(0, 0, 0, 0.4)` backdrop.

## Theming

Every page's `<head>` runs the same four-line bootstrap before first paint:
read `localStorage["theme"]`, fall back to `prefers-color-scheme`, set
`data-theme` on `<html>`. It has to be inline — waiting for a script would
show a flash of the wrong theme.

`static/js/theme.js` then adds the floating toggle (bottom-left, out of the
way of the tasks page's fixed Save Changes button) and writes the choice
back to `localStorage`. One key, one origin, so the preference follows you
from `/tasks` to `/fitness` to `/finance`.

Dark rules are written as `:root[data-theme="dark"]`, never as a bare
`prefers-color-scheme` media query — the toggle has to be able to override
the OS.

### Charts

A `<canvas>` is a baked bitmap: flipping `data-theme` doesn't repaint it.
So chart code never takes a hex color. It takes a **CSS custom property
name**, resolves it against the document at draw time, and redraws on
theme change:

```js
drawSparkline(canvas, values, { colorVar: "--metric-heart-rate" });
```

`static/finance/js/charts.js` registers a `MutationObserver` per chart;
`static/fitness/js/charts.js` shares one observer across every canvas it
has drawn, since a fitness page can have a dozen sparklines up at once.

### Accent scales

Categorical colors get their own token family per section, built to one
formula rather than picked ad hoc — light `oklch(58% 0.14 <hue>)`, dark
`oklch(70% 0.12 <hue>)`, one fixed hue per series:

- `--stock-1..12` (`/finance`) — per-symbol identity colors.
- `--invest-1..4` (`/finance`) — four lightness steps of the Investments
  slice's own green, so the breakdown reads as "what's inside that slice".
- `--metric-*` (`/fitness`) — one per health metric (steps blue, heart
  rate red, sleep violet, and so on).
- `--sleep-deep/rem/light` (`/fitness`) — three lightness steps of the
  Sleep card's violet, same reasoning as `--invest-*`; `--sleep-awake` is
  deliberately warm, because being awake isn't a depth of sleep.

Heart rate zones reuse `--status-blue/green/yellow/red` rather than
defining a fifth family — that already reads as a cool-to-hot intensity
ramp, in both themes.

## Exceptions

Two files hold their own copy of the palette on purpose:

1. **`static/styles/nav.css`** — the nav bar must look identical on any
   page, including one that hasn't loaded `styles.css`.
2. **`roadmap.html`** — a standalone planning document that has to render
   when opened straight off disk, not only when served by
   `backend/server.py`. Its inline tokens are the palette's own values
   under local names; only the status-pill colors are tuned (a step
   darker or lighter) so small uppercase mono text stays legible on its
   own tinted background.

Both still answer to `data-theme`, so the toggle reaches them.

## Adding a page

1. Copy any existing page's `<head>`: charset, **viewport**, the Google
   Fonts link, `styles.css`, `nav.css`, your section's CSS, then the theme
   bootstrap script.
2. `<div id="site-nav"></div>` plus `<script src="/static/js/nav.js">` as
   the first two things in `<body>`.
3. Wrap the content in `.page` &rarr; `.sheet`, with a `<header>` holding
   `.title` and `.meta`.
4. Load `/static/js/theme.js` at the end of `<body>`.
5. Reach for the components above before writing new ones, and put any new
   color in a token — not inline, and not a hex literal in JS.
