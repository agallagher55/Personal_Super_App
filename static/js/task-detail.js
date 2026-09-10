(function () {
  'use strict';

  var form = document.getElementById('task-detail-form');
  var statusEl = document.getElementById('task-detail-status');
  var metaEl = document.getElementById('task-meta');
  var deleteBtn = document.getElementById('delete-task-btn');
  var submitBtn = form.querySelector('.submit-btn');
  submitBtn.disabled = true;

  var fieldSection = document.getElementById('field-section');
  var fieldDesc = document.getElementById('field-desc');
  var fieldNote = document.getElementById('field-note');
  var fieldStatus = document.getElementById('field-status');
  var fieldPriority = document.getElementById('field-priority');
  var fieldFlagTag = document.getElementById('field-flag-tag');
  var fieldTags = document.getElementById('field-tags');
  var fieldNotes = document.getElementById('field-notes');
  var fieldTicketNumber = document.getElementById('field-ticket-number');
  var serviceNowRecordLink = document.getElementById('servicenow-record-link');
  var fieldAssignmentGroup = document.getElementById('field-assignment-group');
  var fieldRequestedBy = document.getElementById('field-requested-by');
  var fieldDueDate = document.getElementById('field-due-date');
  var fieldFocusToday = document.getElementById('field-focus-today');
  var fieldFollowUpDate = document.getElementById('field-follow-up-date');
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

  function updateWorkSectionVisibility() {
    var isWorkTask = fieldSection.value === WORK_SECTION_ID;
    workTypeFields.style.display = isWorkTask ? '' : 'none';
    envFields.style.display = isWorkTask ? '' : 'none';
    if (isWorkTask) {
      updateEnvFieldsVisibility();
    }
  }

  workTypeRadios.forEach(function (radio) {
    radio.addEventListener('change', updateEnvFieldsVisibility);
  });

  fieldSection.addEventListener('change', updateWorkSectionVisibility);

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

  function populateSectionOptions(data, currentSectionId) {
    fieldSection.innerHTML = '';
    (data.sections || []).forEach(function (section) {
      var option = document.createElement('option');
      option.value = section.id;
      option.textContent = section.label;
      fieldSection.appendChild(option);
    });
    fieldSection.value = currentSectionId || '';
  }

  function populateForm(task, section) {
    fieldDesc.value = task.desc || '';
    fieldNote.value = task.note || '';
    fieldStatus.value = task.status || (task.done ? 'done' : 'open');
    fieldPriority.value = task.priority || 'medium';
    fieldNotes.value = task.notes || '';
    fieldTicketNumber.value = task.ticket_number || '';
    if (task.servicenow_sys_id) {
      serviceNowRecordLink.href = 'https://halifaxprod.service-now.com/nav_to.do?uri=task.do?sys_id=' +
        encodeURIComponent(task.servicenow_sys_id);
      serviceNowRecordLink.hidden = false;
    }
    fieldAssignmentGroup.value = task.assignment_group || '';
    fieldRequestedBy.value = task.requested_by || '';
    fieldDueDate.value = task.due_date || '';
    fieldFocusToday.checked = !!task.focus_today;
    fieldFollowUpDate.value = task.follow_up_date || '';
    fieldTimeEstimate.value = task.time_estimate || '';
    fieldRelatedFiles.value = task.related_files || '';
    setWorkType(task.work_type);
    fieldEnvDev.checked = !!task.env_dev;
    fieldEnvQa.checked = !!task.env_qa;
    fieldEnvProd.checked = !!task.env_prod;
    fieldCmdbUpdated.checked = !!task.cmdb_updated;

    updateWorkSectionVisibility();

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

  function getFieldsPayload() {
    return {
      section_id: fieldSection.value,
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
      focus_today: fieldFocusToday.checked,
      follow_up_date: fieldFollowUpDate.value,
      time_estimate: fieldTimeEstimate.value,
      related_files: fieldRelatedFiles.value,
      parent_id: fieldParentId.value,
      work_type: getWorkType(),
      env_dev: fieldEnvDev.checked,
      env_qa: fieldEnvQa.checked,
      env_prod: fieldEnvProd.checked,
      cmdb_updated: fieldCmdbUpdated.checked
    };
  }

  // null until the form is first populated, so a stray 'input'/'change'
  // event fired while the page is still loading can never read as dirty.
  var savedSnapshot = null;
  // Set right before a confirmed in-app navigation proceeds, so the
  // beforeunload handler that fires a moment later (the browser's own
  // "leave site?" prompt) doesn't double up on a warning the user already
  // answered.
  var suppressUnloadGuard = false;
  var UNSAVED_MESSAGE = 'You have unsaved changes on this task. Leave without saving?';

  function isDirty() {
    return savedSnapshot !== null && JSON.stringify(getFieldsPayload()) !== savedSnapshot;
  }

  function markSaved() {
    savedSnapshot = JSON.stringify(getFieldsPayload());
    showStatus('Saved', false);
    submitBtn.disabled = true;
  }

  function handleFieldChange() {
    if (isDirty()) {
      showStatus('Unsaved changes', false);
      submitBtn.disabled = false;
    } else {
      showStatus('Saved', false);
      submitBtn.disabled = true;
    }
  }

  form.addEventListener('input', handleFieldChange);
  form.addEventListener('change', handleFieldChange);

  window.addEventListener('beforeunload', function (e) {
    if (isDirty() && !suppressUnloadGuard) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  // beforeunload alone doesn't cover every way to leave this page: it never
  // fires for a scripted same-page transition, and even for a real link
  // click it only shows the browser's generic, unhelpful prompt. Intercept
  // link clicks directly (in capture phase, ahead of nav.js's plain <a>
  // navigation) so both the nav bar links and the "All tasks" back-link
  // get the same explicit confirmation.
  document.addEventListener('click', function (e) {
    if (!isDirty()) {
      return;
    }
    var link = e.target.closest ? e.target.closest('a[href]') : null;
    if (!link || link.target === '_blank') {
      return;
    }
    if (window.confirm(UNSAVED_MESSAGE)) {
      suppressUnloadGuard = true;
    } else {
      e.preventDefault();
    }
  }, true);

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
        populateSectionOptions(data, found.section ? found.section.id : '');
        populateForm(found.task, found.section);
        markSaved();
      })
      .catch(function (err) {
        showStatus('Failed to load task: ' + err.message, true);
        form.style.display = 'none';
      });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      submitBtn.disabled = true;
      showStatus('Saving...', false);

      fetch('/tasks/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([Object.assign({ id: taskId }, getFieldsPayload())])
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Save failed (status ' + response.status + ')');
          }
          return response.json();
        })
        .then(function () {
          markSaved();
        })
        .catch(function (err) {
          showStatus(err.message, true);
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
          suppressUnloadGuard = true;
          window.location.href = '/tasks';
        })
        .catch(function (err) {
          deleteBtn.disabled = false;
          showStatus(err.message, true);
        });
    });
  }
})();
