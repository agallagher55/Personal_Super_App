import { initThemeToggle } from "../theme.js";

// Reusable app header: page title, the date-range filter form, and an
// optional sync/update control. Every page (the dashboard and each metric
// detail page) used to hand-roll this same markup; centralizing it here
// keeps them in sync and gives each page one place to wire up listeners.
// Also wires up the dark mode toggle (bottom-right corner) - not part of
// the header markup itself, but every page calls this once, which makes it
// the one shared spot to bring the toggle in on every page.
export function renderPageHeader(container, { title, showSync = false } = {}) {
  initThemeToggle();

  container.innerHTML = `
    <h1>${title}</h1>
    <form class="range-controls" id="range-form">
      <label>From <input type="date" id="range-from" /></label>
      <label>To <input type="date" id="range-to" /></label>
      <button type="submit" id="range-apply">Apply</button>
      ${showSync ? `
      <span class="sync-wrap">
        <button type="button" id="sync-now">Sync now</button>
        <span id="last-synced" class="last-synced"></span>
      </span>` : ""}
    </form>
  `;

  return {
    form: container.querySelector("#range-form"),
    from: container.querySelector("#range-from"),
    to: container.querySelector("#range-to"),
    sync: container.querySelector("#sync-now"),
    lastSynced: container.querySelector("#last-synced"),
  };
}
