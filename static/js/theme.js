// Dark mode toggle (bottom-left corner) shared by every page on this site.
// The theme is applied as data-theme on <html>, persisted in localStorage
// under the same "theme" key the fitness pages' own toggle uses (see
// static/fitness/js/theme.js), so the preference carries across the whole
// app, and falls back to the OS preference on first visit. Each page's
// <head> also runs a tiny inline copy of this same read/apply logic so the
// theme is set before first paint - it can't wait for this script, which
// only runs once the page's own scripts do. Bottom-left rather than
// fitness's bottom-right, since index.html already has a fixed
// save-changes-btn/save-status pair in that corner.
(function () {
  var STORAGE_KEY = "theme";

  function preferredTheme() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || localStorage.getItem(STORAGE_KEY) || preferredTheme();
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function initThemeToggle() {
    applyTheme(currentTheme());

    var button = document.createElement("button");
    button.type = "button";
    button.className = "theme-toggle";
    button.setAttribute("aria-label", "Toggle dark mode");

    function sync() {
      var isDark = currentTheme() === "dark";
      button.textContent = isDark ? "☀️" : "🌙";
      button.setAttribute("aria-pressed", String(isDark));
    }

    button.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      localStorage.setItem(STORAGE_KEY, next);
      sync();
    });

    sync();
    document.body.appendChild(button);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initThemeToggle);
  } else {
    initThemeToggle();
  }
})();
