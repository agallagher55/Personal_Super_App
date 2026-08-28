// Universal top nav bar (Tasks / Fitness / Finance + live BTC price),
// shared by every page - renders into the `<div id="site-nav">`
// placeholder each page includes right after <body>, so the markup and
// active-section/price logic live in exactly one place instead of being
// hand-copied (and drifting) across every HTML file. Plain script (not a
// module) so it can be dropped into pages that don't use module scripts.
(function () {
  var SECTIONS = [
    {
      label: "Home",
      href: "/",
      match: function (path) {
        return path === "/";
      },
    },
    {
      label: "Tasks",
      href: "/tasks",
      match: function (path) {
        return path.indexOf("/tasks") === 0 || path.indexOf("/task/") === 0 || path === "/new";
      },
    },
    {
      label: "Fitness",
      href: "/fitness",
      match: function (path) {
        return path.indexOf("/fitness") === 0;
      },
    },
    {
      label: "Finance",
      href: "/finance",
      match: function (path) {
        return path.indexOf("/finance") === 0;
      },
    },
  ];

  function buildNav(container) {
    var path = window.location.pathname;

    var linksHtml = SECTIONS.map(function (section) {
      var active = section.match(path);
      return (
        '<a href="' + section.href + '"' +
        (active ? ' class="is-active" aria-current="page"' : "") +
        ">" + section.label + "</a>"
      );
    }).join("");

    container.innerHTML =
      '<nav class="global-nav">' +
        '<a class="global-nav-brand" href="/">Personal Super App</a>' +
        '<div class="global-nav-links">' + linksHtml + "</div>" +
        '<div class="global-nav-btc" id="global-nav-btc">' +
          '<span class="global-nav-btc-label">BTC</span>' +
          '<span class="global-nav-btc-price" id="global-nav-btc-price">&middot;&middot;&middot;</span>' +
          '<span class="global-nav-btc-change" id="global-nav-btc-change"></span>' +
        "</div>" +
      "</nav>";
  }

  function formatPrice(value) {
    return value.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    });
  }

  function formatChange(pct) {
    var sign = pct > 0 ? "+" : "";
    return sign + pct.toFixed(2) + "%";
  }

  function loadBtcPrice() {
    var wrap = document.getElementById("global-nav-btc");
    var priceEl = document.getElementById("global-nav-btc-price");
    var changeEl = document.getElementById("global-nav-btc-change");
    if (!wrap || !priceEl || !changeEl) return;

    fetch("/finance/api/prices")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var prices = Array.isArray(data.prices) ? data.prices : [];
        var quote = null;
        for (var i = 0; i < prices.length; i++) {
          if (prices[i].symbol === "BTC-USD") {
            quote = prices[i];
            break;
          }
        }
        if (!quote || typeof quote.price !== "number") throw new Error("no BTC price");

        wrap.classList.remove("is-error");
        priceEl.textContent = formatPrice(quote.price);

        // change_pct is null when the upstream gave us a price but no
        // previous close to compare it to - omit the change line entirely
        // rather than coercing it into a false "0.00%".
        if (typeof quote.change_pct === "number") {
          var change = quote.change_pct;
          var direction = change > 0 ? "is-up" : change < 0 ? "is-down" : "is-flat";
          var arrow = change > 0 ? "▲" : change < 0 ? "▼" : "—";
          changeEl.className = "global-nav-btc-change " + direction;
          changeEl.textContent = arrow + " " + formatChange(change);
        } else {
          changeEl.className = "global-nav-btc-change";
          changeEl.textContent = "";
        }
      })
      .catch(function () {
        wrap.classList.add("is-error");
        priceEl.textContent = "--";
        changeEl.textContent = "";
      });
  }

  function init() {
    var container = document.getElementById("site-nav");
    if (!container) return;
    buildNav(container);
    loadBtcPrice();
    setInterval(loadBtcPrice, 60000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
