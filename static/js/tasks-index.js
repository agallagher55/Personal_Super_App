(function () {
  'use strict';

  var list = document.getElementById('toc-list');

  fetch('/tasks.json')
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Could not load tasks.json (status ' + response.status + ')');
      }
      return response.json();
    })
    .then(function (data) {
      list.innerHTML = '';

      data.sections.forEach(function (section) {
        var tasks = section.tasks || [];
        var openCount = tasks.filter(function (t) { return !t.done; }).length;
        var closedCount = tasks.length - openCount;

        var li = document.createElement('li');
        li.className = 'toc-item';

        var link = document.createElement('a');
        link.className = 'toc-link';
        link.href = '/tasks/' + section.slug;

        var label = document.createElement('span');
        label.className = 'toc-label';
        label.textContent = section.label;

        var countEl = document.createElement('span');
        countEl.className = 'toc-count';
        countEl.textContent = openCount + ' open · ' + closedCount + ' closed';

        link.appendChild(label);
        link.appendChild(countEl);
        li.appendChild(link);
        list.appendChild(li);
      });

      if (data.sections.length === 0) {
        var empty = document.createElement('li');
        empty.className = 'toc-item toc-loading';
        empty.textContent = 'No categories found.';
        list.appendChild(empty);
      }
    })
    .catch(function (err) {
      list.innerHTML = '';
      var errorItem = document.createElement('li');
      errorItem.className = 'toc-item toc-loading';
      errorItem.textContent = 'Failed to load categories: ' + err.message;
      list.appendChild(errorItem);
    });
})();