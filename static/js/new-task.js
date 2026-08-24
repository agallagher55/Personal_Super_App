(function () {
  'use strict';

  var select = document.getElementById('section-select');
  var parentSelect = document.getElementById('parent-select');
  var workTypeFields = document.getElementById('work-type-fields');
  var WORK_SECTION_ID = 'own-tasks';

  function updateWorkTypeVisibility() {
    workTypeFields.style.display = select.value === WORK_SECTION_ID ? '' : 'none';
  }

  select.addEventListener('change', updateWorkTypeVisibility);

  fetch('/tasks.json')
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Could not load tasks.json (status ' + response.status + ')');
      }
      return response.json();
    })
    .then(function (data) {
      select.innerHTML = '';
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.disabled = true;
      placeholder.selected = true;
      placeholder.textContent = 'Choose a section...';
      select.appendChild(placeholder);

      var preselectId = new URLSearchParams(window.location.search).get('section');

      data.sections.forEach(function (section) {
        var option = document.createElement('option');
        option.value = section.id;
        option.textContent = section.label;
        select.appendChild(option);

        (section.tasks || []).forEach(function (task) {
          var parentOption = document.createElement('option');
          parentOption.value = task.id;
          parentOption.textContent = section.label + ': ' + task.desc;
          parentSelect.appendChild(parentOption);
        });
      });

      if (preselectId) {
        var match = Array.prototype.slice.call(select.options).filter(function (opt) {
          return opt.value === preselectId;
        })[0];
        if (match) {
          match.selected = true;
          placeholder.selected = false;
        }
      }

      updateWorkTypeVisibility();
    })
    .catch(function (err) {
      select.innerHTML = '';
      var option = document.createElement('option');
      option.value = '';
      option.textContent = 'Failed to load sections: ' + err.message;
      select.appendChild(option);
    });
})();