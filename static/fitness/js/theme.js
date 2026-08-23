// Dark mode toggle (bottom-right corner) shared by every page. The theme is
// applied as data-theme on <html>, persisted in localStorage, and falls back
// to the OS preference on first visit. Each page's <head> also runs a tiny
// inline copy of this same read/apply logic (see pages/*.html) so the theme
// is set before first paint - it can't wait for this module, which only
// loads once the deferred `type="module"` page script runs.
const STORAGE_KEY = "theme";

function preferredTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || localStorage.getItem(STORAGE_KEY) || preferredTheme();
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

export function initThemeToggle() {
  applyTheme(currentTheme());

  const button = document.createElement("button");
  button.type = "button";
  button.className = "theme-toggle";
  button.setAttribute("aria-label", "Toggle dark mode");

  function sync() {
    const isDark = currentTheme() === "dark";
    button.textContent = isDark ? "☀️" : "🌙";
    button.setAttribute("aria-pressed", String(isDark));
  }

  button.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    localStorage.setItem(STORAGE_KEY, next);
    sync();
  });

  sync();
  document.body.appendChild(button);
}
