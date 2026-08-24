(function () {
  'use strict';

  var form = document.getElementById('task-detail-form');
  var statusEl = document.getElementById('task-detail-status');
  var metaEl = document.getElementById('task-meta');
  var deleteBtn = document.getElementById('delete-task-btn');

  var fieldDesc = document.getElementById('field-desc');
  var fieldNote = document.getElementById('field-note');
  var fieldStatus = document.getElementById('field-status');
  var fieldPriority = document.getElementById('field-priority');
  var fieldFlagTag = document.getElementById('field-flag-tag');
  var fieldTags = document.getElementById('field-tags');
  var fieldNotes = document.getElementById('field-notes');
  var fieldTicketNumber = document.getElementById('field-ticket-number');
  var fieldAssignmentGroup = document.getElementById('field-assignment-group');
  var fieldRequestedBy = document.getElementById('field-requested-by');
  var fieldDueDate = document.getElementById('field-due-date');
  var fieldTimeEstimate = document.getElementById('field-time-estimate');
  var fieldRelatedFiles = document.getElementById('field-related-files');
  var fieldParentId = document.getElementById('field-parent-id');
  var workTypeRadios = document.querySelectorAll('input[name="work_type"]');
  var fieldEnvDev = document.getElementById('field-env-dev');
  var fieldEnvQa = document.getElementById('field-env-qa');
  var fieldEnvProd = document.getElementById('field-env-prod');
  var fieldCmdbUpdated = document.getElementById('field-cmdb-updated');
  var workTypeFields = document.getElementById('detail-work-type-fields');
  var envFields = document.getElementById('detail-env-fields');
  var cmdbField = document.getElementById('detail-cmdb-field');
  var WORK_SECTION_ID = 'own-tasks';

  function getWorkType() {
    var checked = document.querySelector('input[name="work_type"]:checked');
    return checked ? checked.value : '';
  }

  function setWorkType(value) {
    workTypeRadios.forEach(function (radio) {
      radio.checked = radio.value === (value || '');
    });
  }

  function updateEnvFieldsVisibility() {
    var workType = getWorkType();
    envFields.style.display = workType ? '' : 'none';
    cmdbField.style.display = workType === 'new-feature' ? '' : 'none';
  }

  workTypeRadios.forEach(function (radio) {
    radio.addEventListener('change', updateEnvFieldsVisibility);
  });

  function getTaskIdFromPath() {
    var match = window.location.pathname.match(/^\/task\/([^/]+)$/);
    return match ? match[1] : null;
  }

  var taskId = getTaskIdFromPath();

  function showStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.classList.toggle('error', !!isError);
    statusEl.classList.add('show');
  }

  function formatDate(iso) {
    if (!iso) {
      return '—';
    }
    var d = new Date(iso);
    if (isNaN(d.getTime())) {
      return iso;
    }
    return d.toLocaleString();
  }

  function findTask(data, id) {
    var sections = data.sections || [];
    for (var i = 0; i < sections.length; i++) {
      var tasks = sections[i].tasks || [];
      for (var j = 0; j < tasks.length; j++) {
        if (tasks[j].id === id) {
          return { task: tasks[j], section: sections[i] };
        }
      }
    }
    return null;
  }

  function populateParentOptions(data, task) {
    (data.sections || []).forEach(function (section) {
      (section.tasks || []).forEach(function (candidate) {
        if (candidate.id === task.id) {
          return;
        }
        var option = document.createElement('option');
        option.value = candidate.id;
        option.textContent = section.label + ': ' + candidate.desc;
        fieldParentId.appendChild(option);
      });
    });
    fieldParentId.value = task.parent_id || '';
  }

  function populateForm(task, section) {
    fieldDesc.value = task.desc || '';
    fieldNote.value = task.note || '';
    fieldStatus.value = task.status || (task.done ? 'done' : 'open');
    fieldPriority.value = task.priority || 'medium';
    fieldNotes.value = task.notes || '';
    fieldTicketNumber.value = task.ticket_number || '';
    fieldAssignmentGroup.value = task.assignment_group || '';
    fieldRequestedBy.value = task.requested_by || '';
    fieldDueDate.value = task.due_date || '';
    fieldTimeEstimate.value = task.time_estimate || '';
    fieldRelatedFiles.value = task.related_files || '';
    setWorkType(task.work_type);
    fieldEnvDev.checked = !!task.env_dev;
    fieldEnvQa.checked = !!task.env_qa;
    fieldEnvProd.checked = !!task.env_prod;
    fieldCmdbUpdated.checked = !!task.cmdb_updated;

    var isWorkTask = section && section.id === WORK_SECTION_ID;
    workTypeFields.style.display = isWorkTask ? '' : 'none';
    envFields.style.display = isWorkTask ? '' : 'none';
    if (isWorkTask) {
      updateEnvFieldsVisibility();
    }

    var tags = task.tags || [];
    var flagTag = tags.filter(function (t) { return t.flag; })[0];
    var otherTags = tags.filter(function (t) { return !t.flag; });
    fieldFlagTag.value = flagTag ? flagTag.text : '';
    fieldTags.value = otherTags.map(function (t) { return t.text; }).join(', ');

    document.title = (task.desc || 'Task') + ' - Personal Tasks';

    var metaParts = [];
    metaParts.push('<a class="back-link" href="/tasks">&larr; All tasks</a>');
    metaParts.push((section && section.label ? section.label : 'Unknown section'));
    metaParts.push('Created ' + formatDate(task.created));
    metaParts.push('Modified ' + formatDate(task.modified));
    if (task.completed) {
      metaParts.push('Completed ' + formatDate(task.completed));
    }
    metaEl.innerHTML = metaParts.join('<br>');
  }

  function buildTagsPayload() {
    var tags = [];
    var flagText = fieldFlagTag.value.trim();
    if (flagText) {
      tags.push({ text: flagText, flag: true });
    }
    fieldTags.value.split(',').forEach(function (raw) {
      var text = raw.trim();
      if (text) {
        tags.push({ text: text, flag: false });
      }
    });
    return tags;
  }

  if (!taskId) {
    showStatus('No task specified.', true);
    form.style.display = 'none';
  } else {
    fetch('/tasks.json')
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Could not load tasks.json (status ' + response.status + ')');
        }
        return response.json();
      })
      .then(function (data) {
        var found = findTask(data, taskId);
        if (!found) {
          showStatus('Task not found.', true);
          form.style.display = 'none';
          return;
        }
        populateParentOptions(data, found.task);
        populateForm(found.task, found.section);
      })
      .catch(function (err) {
        showStatus('Failed to load task: ' + err.message, true);
        form.style.display = 'none';
      });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var submitBtn = form.querySelector('.submit-btn');
      submitBtn.disabled = true;

      fetch('/tasks/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([{
          id: taskId,
          desc: fieldDesc.value,
          note: fieldNote.value,
          status: fieldStatus.value,
          priority: fieldPriority.value,
          tags: buildTagsPayload(),
          notes: fieldNotes.value,
          ticket_number: fieldTicketNumber.value,
          assignment_group: fieldAssignmentGroup.value,
          requested_by: fieldRequestedBy.value,
          due_date: fieldDueDate.value,
          time_estimate: fieldTimeEstimate.value,
          related_files: fieldRelatedFiles.value,
          parent_id: fieldParentId.value,
          work_type: getWorkType(),
          env_dev: fieldEnvDev.checked,
          env_qa: fieldEnvQa.checked,
          env_prod: fieldEnvProd.checked,
          cmdb_updated: fieldCmdbUpdated.checked
        }])
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Save failed (status ' + response.status + ')');
          }
          return response.json();
        })
        .then(function () {
          showStatus('Saved', false);
        })
        .catch(function (err) {
          showStatus(err.message, true);
        })
        .finally(function () {
          submitBtn.disabled = false;
        });
    });

    deleteBtn.addEventListener('click', function () {
      var confirmed = window.confirm(
        'Permanently delete "' + fieldDesc.value + '"? This cannot be undone.'
      );
      if (!confirmed) {
        return;
      }

      deleteBtn.disabled = true;
      fetch('/tasks/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: taskId })
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Delete failed (status ' + response.status + ')');
          }
          return response.json();
        })
        .then(function () {
          window.location.href = '/tasks';
        })
        .catch(function (err) {
          deleteBtn.disabled = false;
          showStatus(err.message, true);
        });
    });
  }
})();
