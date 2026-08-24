// Dashboard hub for "/" - pulls one live summary per section (Tasks,
// Fitness, Finance) from each section's own existing endpoint and links
// through to it. Plain script (not a module), matching nav.js/tasks-index.js.
(function () {
  'use strict';

  var dateEl = document.getElementById('home-date');
  if (dateEl) {
    dateEl.textContent = new Date().toLocaleDateString('en-US', {
      weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'
    });
  }

  function setCard(metricId, subId, metricText, subText) {
    var metricEl = document.getElementById(metricId);
    var subEl = document.getElementById(subId);
    if (metricEl) metricEl.textContent = metricText;
    if (subEl) subEl.textContent = subText;
  }

  function loadTasks() {
    fetch('/tasks.json')
      .then(function (res) {
        if (!res.ok) throw new Error('status ' + res.status);
        return res.json();
      })
      .then(function (data) {
        var sections = data.sections || [];
        var openCount = 0;
        sections.forEach(function (section) {
          (section.tasks || []).forEach(function (t) {
            if (!t.done) openCount += 1;
          });
        });
        setCard('home-tasks-metric', 'home-tasks-sub',
          openCount + ' open',
          sections.length + ' categories');
      })
      .catch(function () {
        setCard('home-tasks-metric', 'home-tasks-sub', '--', 'Unable to load tasks');
      });
  }

  function loadFitness() {
    fetch('/fitness/api/metrics')
      .then(function (res) {
        if (!res.ok) throw new Error('status ' + res.status);
        return res.json();
      })
      .then(function (data) {
        var steps = (data.metrics && data.metrics.steps) || [];
        var latest = steps[steps.length - 1];
        if (!latest) {
          setCard('home-fitness-metric', 'home-fitness-sub', '--', 'No steps logged this week');
          return;
        }
        setCard('home-fitness-metric', 'home-fitness-sub',
          latest.value.toLocaleString() + ' steps',
          'on ' + latest.date);
      })
      .catch(function () {
        setCard('home-fitness-metric', 'home-fitness-sub', '--', 'Unable to load fitness data');
      });
  }

  function loadFinance() {
    fetch('/finance/api/prices')
      .then(function (res) {
        if (!res.ok) throw new Error('status ' + res.status);
        return res.json();
      })
      .then(function (data) {
        var prices = Array.isArray(data.prices) ? data.prices : [];
        var btc = null;
        for (var i = 0; i < prices.length; i++) {
          if (prices[i].symbol === 'BTC-USD') {
            btc = prices[i];
            break;
          }
        }
        if (!btc || typeof btc.price !== 'number') {
          setCard('home-finance-metric', 'home-finance-sub', '--', 'BTC price unavailable');
          return;
        }
        var change = btc.change_pct || 0;
        var sign = change > 0 ? '+' : '';
        setCard('home-finance-metric', 'home-finance-sub',
          btc.price.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }),
          'BTC ' + sign + change.toFixed(2) + '%');
      })
      .catch(function () {
        setCard('home-finance-metric', 'home-finance-sub', '--', 'Unable to load market data');
      });
  }

  loadTasks();
  loadFitness();
  loadFinance();
})();
