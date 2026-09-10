(function () {
  'use strict';

  var sectionsContainer = document.getElementById('sections');
  var footnoteEl = document.getElementById('footnote-text');
  var completedHeader = document.getElementById('completed-header');
  var completedToggle = document.getElementById('completed-toggle');
  var completedBody = document.getElementById('completed-body');
  var completedCountEl = document.getElementById('completed-count');
  var completedFilterBar = document.getElementById('completed-filter-bar');
  var completedCategoryFilter = 'all';
  var taskUrlParams = new URLSearchParams(window.location.search);
  var requestedTaskView = taskUrlParams.get('view');
  // All remains the safe default. A focused queue can legitimately contain
  // zero items; opening on one made a populated database look empty.
  var activeTaskView = requestedTaskView || 'all';
  var taskViewBar = document.getElementById('task-view-bar');
  var taskFacetBar = document.getElementById('task-facet-bar');
  var taskViewEmpty = document.getElementById('task-view-empty');
  var syncHealthEl = document.getElementById('sync-health');
  var previousSuccessfulSyncStartedAt = '';
  var TASK_FACETS = ['status', 'priority', 'ticket_type', 'assignment_group', 'origin', 'freshness'];
  var activeTaskFilters = {};
  TASK_FACETS.forEach(function (facet) {
    activeTaskFilters[facet] = taskUrlParams.getAll(facet);
  });
  var activeTaskSort = taskUrlParams.get('sort') || 'personal';

  var sectionListMap = {};    // sectionId -> main <ol> in the left column
  var sectionLabelMap = {};   // sectionId -> section label text
  var completedGroupMap = {}; // sectionId -> <ol> inside the completed panel
  var taskById = {};          // task id -> task data, for resolving parent_id

  var WORK_SECTION_ID = 'own-tasks';
  var ENVIRONMENTS = ['dev', 'qa', 'prod'];

  var DAY_NAMES = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  var MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

  // The viewer's own local calendar date as YYYY-MM-DD - never the
  // server's, and never UTC (Date#toISOString would silently roll over at
  // the wrong wall-clock hour for anyone west of UTC).
  function getLocalDateString(date) {
    var d = date || new Date();
    var month = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + month + '-' + day;
  }

  // date +/- days, both sides plain YYYY-MM-DD strings. Built from local
  // (not UTC) Date components throughout, same reasoning as above, and
  // goes through the Date constructor rather than string math so month/
  // year rollovers (and DST, where applicable) are handled correctly.
  function addDaysToDateString(dateString, delta) {
    var parts = dateString.split('-').map(Number);
    var d = new Date(parts[0], parts[1] - 1, parts[2]);
    d.setDate(d.getDate() + delta);
    return getLocalDateString(d);
  }

  // "SEP 8" - the day-nav buttons' label, matching this page's existing
  // all-caps date style (see the page-date header below).
  function formatShortDate(dateString) {
    var parts = dateString.split('-').map(Number);
    return MONTH_NAMES[parts[1] - 1] + ' ' + parts[2];
  }

  var pageDateEl = document.getElementById('page-date');
  if (pageDateEl) {
    var today = new Date();
    pageDateEl.textContent = DAY_NAMES[today.getDay()] + ' ' + MONTH_NAMES[today.getMonth()] +
      ' ' + today.getDate() + ', ' + today.getFullYear();
  }

  var STATUS_LABELS = {
    open: 'Open',
    'in-progress': 'In Progress',
    pending: 'Pending',
    done: 'Done',
    cancelled: 'Cancelled'
  };
  var PRIORITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High' };
  var WORK_TYPE_LABELS = { 'new-feature': 'New Feature', 'schema-change': 'Schema Change' };

  function formatDate(iso) {
    if (!iso) {
      return '';
    }
    var d = new Date(iso);
    if (isNaN(d.getTime())) {
      return '';
    }
    return MONTH_NAMES[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
  }

  function formatRelativeTime(iso) {
    var then = new Date(iso);
    if (isNaN(then.getTime())) {
      return 'at an unknown time';
    }
    var minutes = Math.max(0, Math.floor((Date.now() - then.getTime()) / 60000));
    if (minutes < 1) {
      return 'just now';
    }
    if (minutes < 60) {
      return minutes + ' min ago';
    }
    var hours = Math.floor(minutes / 60);
    if (hours < 48) {
      return hours + ' hr ago';
    }
    return Math.floor(hours / 24) + ' days ago';
  }

  function sourceAgeLabel(sourceOpenedAt) {
    if (!sourceOpenedAt) {
      return '';
    }
    var opened = new Date(sourceOpenedAt);
    if (isNaN(opened.getTime())) {
      return '';
    }
    var days = Math.max(0, Math.floor((Date.now() - opened.getTime()) / 86400000));
    if (days < 1) {
      return 'opened today';
    }
    if (days < 30) {
      return 'opened ' + days + 'd ago';
    }
    if (days < 365) {
      return 'opened ' + Math.floor(days / 30) + 'mo ago';
    }
    return 'opened ' + Math.floor(days / 365) + 'y ago';
  }

  function changedSincePreviousSync(taskData) {
    return !!(previousSuccessfulSyncStartedAt && taskData.source_updated_at &&
      taskData.source_updated_at > previousSuccessfulSyncStartedAt);
  }

  function renderSyncHealth(status) {
    if (!syncHealthEl) {
      return;
    }
    var latest = status && status.latest_run;
    syncHealthEl.classList.toggle('error', !!(latest && latest.result === 'error'));
    if (!latest) {
      syncHealthEl.textContent = 'ServiceNow · never synced';
    } else if (latest.result === 'error') {
      syncHealthEl.textContent = 'ServiceNow · last sync failed ' + formatRelativeTime(latest.finished_at);
    } else {
      var changed = document.querySelectorAll('.field-pill-source-changed').length;
      syncHealthEl.textContent = 'ServiceNow · synced ' + formatRelativeTime(latest.finished_at) +
        ' · ' + latest.records_seen + ' active · ' + changed + ' changed';
    }
  }

  function buildTag(tag) {
    var span = document.createElement('span');
    span.className = tag.flag ? 'tag flag' : 'tag';
    span.textContent = tag.text;
    return span;
  }

  function buildTask(taskData, sectionId) {
    var status = taskData.status || (taskData.done ? 'done' : 'open');
    var priority = taskData.priority && PRIORITY_LABELS[taskData.priority] ? taskData.priority : 'medium';

    var li = document.createElement('li');
    li.className = 'task priority-' + priority +
      (status === 'done' ? ' done' : '') +
      (status === 'in-progress' ? ' in-progress' : '') +
      (status === 'pending' ? ' pending' : '') +
      (status === 'cancelled' ? ' cancelled' : '');
    li.className += ' task-collapsed';
    li.dataset.section = sectionId;
    li.dataset.taskId = taskData.id || '';
    li.dataset.status = status;
    li.dataset.priority = priority;
    li.dataset.focusToday = taskData.focus_today ? 'true' : 'false';
    li.dataset.dueDate = taskData.due_date || '';
    li.dataset.followUpDate = taskData.follow_up_date || '';
    li.dataset.ticketType = ticketTypeFor(taskData.ticket_number);
    li.dataset.assignmentGroup = taskData.assignment_group || '';
    li.dataset.origin = taskData.ticket_number ? 'service-now' : 'local';
    li.dataset.freshness = changedSincePreviousSync(taskData) ? 'changed' : '';
    li.dataset.modified = taskData.modified || '';
    li.dataset.sourceOpenedAt = taskData.source_opened_at || '';
    li.dataset.created = taskData.created || '';

    var handle = document.createElement('span');
    handle.className = 'drag-handle';
    handle.setAttribute('draggable', 'true');
    handle.setAttribute('aria-hidden', 'true');
    handle.title = 'Drag to reorder';
    handle.textContent = '⋮⋮';

    var reorderControls = document.createElement('div');
    reorderControls.className = 'task-reorder-controls';

    var taskMoveUpBtn = document.createElement('button');
    taskMoveUpBtn.type = 'button';
    taskMoveUpBtn.className = 'task-move-btn task-move-up';
    taskMoveUpBtn.setAttribute('aria-label', 'Move task up');
    taskMoveUpBtn.textContent = '↑';

    var taskMoveDownBtn = document.createElement('button');
    taskMoveDownBtn.type = 'button';
    taskMoveDownBtn.className = 'task-move-btn task-move-down';
    taskMoveDownBtn.setAttribute('aria-label', 'Move task down');
    taskMoveDownBtn.textContent = '↓';

    reorderControls.appendChild(taskMoveUpBtn);
    reorderControls.appendChild(taskMoveDownBtn);

    var num = document.createElement(taskData.id ? 'a' : 'div');
    num.className = 'num';
    if (taskData.id) {
      num.href = '/task/' + encodeURIComponent(taskData.id);
      num.title = 'Open task';
    }

    var statusSelect = document.createElement('select');
    statusSelect.className = 'status-select';
    Object.keys(STATUS_LABELS).forEach(function (value) {
      var option = document.createElement('option');
      option.value = value;
      option.textContent = STATUS_LABELS[value];
      if (value === status) {
        option.selected = true;
      }
      statusSelect.appendChild(option);
    });

    var prioritySelect = document.createElement('select');
    prioritySelect.className = 'priority-select';
    Object.keys(PRIORITY_LABELS).forEach(function (value) {
      var option = document.createElement('option');
      option.value = value;
      option.textContent = PRIORITY_LABELS[value];
      if (value === priority) {
        option.selected = true;
      }
      prioritySelect.appendChild(option);
    });

    var body = document.createElement('div');
    body.className = 'body';

    var descRow = document.createElement('button');
    descRow.type = 'button';
    descRow.className = 'desc-row';
    // Every card starts with the task-collapsed class (set above on li),
    // so the toggle starts in sync with that.
    descRow.setAttribute('aria-expanded', 'false');

    var toggleArrow = document.createElement('span');
    toggleArrow.className = 'task-toggle-arrow';
    toggleArrow.innerHTML = '&#9660;';
    toggleArrow.setAttribute('aria-hidden', 'true');

    var desc = document.createElement('div');
    desc.className = 'desc';
    desc.textContent = taskData.desc;

    descRow.appendChild(toggleArrow);
    descRow.appendChild(desc);
    body.appendChild(descRow);

    var details = document.createElement('div');
    details.className = 'task-details';
    if (taskData.id) {
      details.id = 'task-details-' + taskData.id;
      descRow.setAttribute('aria-controls', details.id);
    }
    body.appendChild(details);

    descRow.addEventListener('click', function () {
      var collapsed = li.classList.toggle('task-collapsed');
      descRow.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });

    if (taskData.note) {
      var note = document.createElement('div');
      note.className = 'note';
      note.textContent = taskData.note;
      details.appendChild(note);
    }

    var parentTask = taskData.parent_id ? taskById[taskData.parent_id] : null;
    var isWorkTask = sectionId === WORK_SECTION_ID;

    var fieldEntries = [
      { key: 'ticket_number', label: '', className: 'ticket' },
      { key: 'assignment_group', label: '', className: 'group' },
      { key: 'requested_by', label: 'req: ', className: 'requester' },
      { key: 'related_files', label: 'files: ', className: 'files' },
      { key: 'parent_id', label: 'parent: ', className: 'parent', value: parentTask ? parentTask.desc : '' }
    ].filter(function (entry) {
      return entry.value !== undefined ? entry.value : taskData[entry.key];
    });
    if (isWorkTask && changedSincePreviousSync(taskData)) {
      fieldEntries.push({ value: 'Changed', className: 'source-changed' });
    }
    if (isWorkTask && sourceAgeLabel(taskData.source_opened_at)) {
      fieldEntries.push({ value: sourceAgeLabel(taskData.source_opened_at), className: 'source-age' });
    }

    if (fieldEntries.length > 0) {
      var fields = document.createElement('div');
      fields.className = 'task-fields';
      fieldEntries.forEach(function (entry) {
        var pill = document.createElement(
          entry.key === 'ticket_number' && taskData.servicenow_sys_id ? 'a' : 'span'
        );
        pill.className = 'field-pill field-pill-' + entry.className;
        var value = entry.value !== undefined ? entry.value : taskData[entry.key];
        pill.textContent = entry.label + value;
        if (pill.tagName === 'A') {
          pill.href = 'https://halifaxprod.service-now.com/nav_to.do?uri=task.do?sys_id=' +
            encodeURIComponent(taskData.servicenow_sys_id);
          pill.target = '_blank';
          pill.rel = 'noopener noreferrer';
          pill.title = 'Open in ServiceNow';
        }
        fields.appendChild(pill);
      });
      details.appendChild(fields);
    }

    var quickFields = document.createElement('div');
    quickFields.className = 'task-quick-fields';

    var dueField = document.createElement('label');
    dueField.className = 'quick-field';
    var dueFieldLabel = document.createElement('span');
    dueFieldLabel.className = 'quick-field-label';
    dueFieldLabel.textContent = 'Due';
    var dueInput = document.createElement('input');
    dueInput.type = 'date';
    dueInput.className = 'due-date-input';
    dueInput.value = taskData.due_date || '';
    dueField.appendChild(dueFieldLabel);
    dueField.appendChild(dueInput);

    var estimateField = document.createElement('label');
    estimateField.className = 'quick-field';
    var estimateFieldLabel = document.createElement('span');
    estimateFieldLabel.className = 'quick-field-label';
    estimateFieldLabel.textContent = 'Est. hrs';
    var estimateInput = document.createElement('input');
    estimateInput.type = 'number';
    estimateInput.className = 'time-estimate-input';
    estimateInput.min = '0';
    estimateInput.step = '0.5';
    estimateInput.value = taskData.time_estimate || '';
    estimateField.appendChild(estimateFieldLabel);
    estimateField.appendChild(estimateInput);

    quickFields.appendChild(dueField);

    var todayField = document.createElement('label');
    todayField.className = 'quick-field today-field';
    var todayInput = document.createElement('input');
    todayInput.type = 'checkbox';
    todayInput.className = 'focus-today-input';
    todayInput.checked = !!taskData.focus_today;
    var todayLabel = document.createElement('span');
    todayLabel.className = 'quick-field-label';
    todayLabel.textContent = 'Today';
    todayField.appendChild(todayInput);
    todayField.appendChild(todayLabel);
    quickFields.appendChild(todayField);

    var followUpField = document.createElement('label');
    followUpField.className = 'quick-field';
    var followUpLabel = document.createElement('span');
    followUpLabel.className = 'quick-field-label';
    followUpLabel.textContent = 'Follow up';
    var followUpInput = document.createElement('input');
    followUpInput.type = 'date';
    followUpInput.className = 'follow-up-date-input';
    followUpInput.value = taskData.follow_up_date || '';
    followUpField.appendChild(followUpLabel);
    followUpField.appendChild(followUpInput);
    quickFields.appendChild(followUpField);
    quickFields.appendChild(estimateField);
    details.appendChild(quickFields);

    if (isWorkTask && taskData.work_type && WORK_TYPE_LABELS[taskData.work_type]) {
      var workTypeTags = document.createElement('div');
      workTypeTags.className = 'task-fields';
      var workTypePill = document.createElement('span');
      workTypePill.className = 'field-pill field-pill-worktype';
      workTypePill.textContent = WORK_TYPE_LABELS[taskData.work_type];
      workTypeTags.appendChild(workTypePill);
      details.appendChild(workTypeTags);

      var envFields = document.createElement('div');
      envFields.className = 'task-env-fields';
      ENVIRONMENTS.forEach(function (env) {
        var envField = document.createElement('label');
        envField.className = 'env-field';
        var envInput = document.createElement('input');
        envInput.type = 'checkbox';
        envInput.className = 'env-' + env + '-input';
        envInput.checked = !!taskData['env_' + env];
        var envLabel = document.createElement('span');
        envLabel.className = 'quick-field-label';
        envLabel.textContent = env.toUpperCase();
        envField.appendChild(envInput);
        envField.appendChild(envLabel);
        envFields.appendChild(envField);
      });

      if (taskData.work_type === 'new-feature') {
        var cmdbField = document.createElement('label');
        cmdbField.className = 'env-field';
        var cmdbInput = document.createElement('input');
        cmdbInput.type = 'checkbox';
        cmdbInput.className = 'cmdb-updated-input';
        cmdbInput.checked = !!taskData.cmdb_updated;
        var cmdbLabel = document.createElement('span');
        cmdbLabel.className = 'quick-field-label';
        cmdbLabel.textContent = 'CMDB';
        cmdbField.appendChild(cmdbInput);
        cmdbField.appendChild(cmdbLabel);
        envFields.appendChild(cmdbField);
      }

      details.appendChild(envFields);
    }

    if (taskData.tags && taskData.tags.length > 0) {
      var tags = document.createElement('div');
      tags.className = 'tags';
      taskData.tags.forEach(function (tag) {
        tags.appendChild(buildTag(tag));
      });
      details.appendChild(tags);
    }

    var meta = document.createElement('div');
    meta.className = 'task-meta';
    if (status === 'done' && taskData.completed) {
      meta.textContent = 'Completed ' + formatDate(taskData.completed);
    } else if (taskData.created) {
      var metaText = 'Created ' + formatDate(taskData.created);
      if (taskData.modified && taskData.modified !== taskData.created) {
        metaText += ' · Updated ' + formatDate(taskData.modified);
      }
      meta.textContent = metaText;
    }
    if (meta.textContent) {
      details.appendChild(meta);
    }

    var notesLabel = document.createElement('div');
    notesLabel.className = 'notes-label';
    notesLabel.textContent = 'Notes';
    details.appendChild(notesLabel);

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add notes...';
    textarea.value = taskData.notes || '';
    textarea.className = 'notes-input';
    details.appendChild(textarea);

    var deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'delete-btn';
    deleteBtn.innerHTML = '&times;';
    deleteBtn.title = 'Delete task';
    deleteBtn.setAttribute('aria-label', 'Delete task');

    var controls = document.createElement('div');
    controls.className = 'task-controls';
    controls.appendChild(statusSelect);
    controls.appendChild(prioritySelect);

    li.appendChild(handle);
    li.appendChild(reorderControls);
    li.appendChild(num);
    li.appendChild(controls);
    li.appendChild(body);
    li.appendChild(deleteBtn);

    taskMoveUpBtn.addEventListener('click', function () { moveTask(li, -1); });
    taskMoveDownBtn.addEventListener('click', function () { moveTask(li, 1); });

    handle.addEventListener('dragstart', function (e) {
      li.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', taskData.id || '');
      if (e.dataTransfer.setDragImage) {
        e.dataTransfer.setDragImage(li, 20, 20);
      }
    });

    handle.addEventListener('dragend', function () {
      li.classList.remove('dragging');
      var list = li.closest('ol.tasks');
      if (list) {
        renumber(list);
      }
    });

    prioritySelect.addEventListener('change', function () {
      li.classList.remove('priority-' + li.dataset.priority);
      li.dataset.priority = prioritySelect.value;
      li.classList.add('priority-' + prioritySelect.value);
      sortTaskLists();
      applySearchFilter();
    });

    todayInput.addEventListener('change', function () {
      li.dataset.focusToday = todayInput.checked ? 'true' : 'false';
      updateViewCounts();
      applySearchFilter();
    });

    statusSelect.addEventListener('change', function () {
      var newStatus = statusSelect.value;
      var wasInCompleted = completedBody.contains(li);

      li.dataset.status = newStatus;
      li.classList.toggle('in-progress', newStatus === 'in-progress');
      li.classList.toggle('pending', newStatus === 'pending');
      li.classList.toggle('cancelled', newStatus === 'cancelled');
      updateViewCounts();

      if (newStatus === 'done') {
        moveToCompleted(li, sectionId);
      } else if (wasInCompleted) {
        moveToActive(li, sectionId);
      } else {
        li.classList.remove('done');
        updateSectionCount(sectionId);
      }
      applySearchFilter();
    });

    deleteBtn.addEventListener('click', function () {
      var confirmed = window.confirm(
        'Permanently delete "' + taskData.desc + '"? This cannot be undone.'
      );
      if (confirmed) {
        deleteTask(li, taskData.id, sectionId);
      }
    });

    return li;
  }

  // Keyboard-only equivalent of dragging a task's handle: swaps it with the
  // sibling in `direction` (-1 up, 1 down) within whichever list currently
  // holds it (the section's own list, or a completed group's), then
  // renumbers exactly as dragend already does.
  function moveTask(li, direction) {
    var list = li.closest('ol.tasks');
    if (!list) {
      return;
    }
    var sibling = direction < 0 ? li.previousElementSibling : li.nextElementSibling;
    if (!sibling) {
      return;
    }
    if (direction < 0) {
      list.insertBefore(li, sibling);
    } else {
      list.insertBefore(sibling, li);
    }
    renumber(list);
  }

  function getTaskDragAfterElement(list, y) {
    var elements = Array.prototype.slice.call(list.querySelectorAll(':scope > .task:not(.dragging)'));
    return elements.reduce(function (closest, child) {
      var box = child.getBoundingClientRect();
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset: offset, element: child };
      }
      return closest;
    }, { offset: -Infinity, element: null }).element;
  }

  function attachTaskReorder(list) {
    list.addEventListener('dragover', function (e) {
      var dragging = list.querySelector('.task.dragging');
      if (!dragging) {
        return;
      }
      e.preventDefault();
      var afterElement = getTaskDragAfterElement(list, e.clientY);
      if (afterElement == null) {
        list.appendChild(dragging);
      } else {
        list.insertBefore(dragging, afterElement);
      }
    });
  }

  function ensureCompletedGroup(sectionId) {
    if (completedGroupMap[sectionId]) {
      return completedGroupMap[sectionId];
    }

    var group = document.createElement('div');
    group.className = 'completed-group';
    group.dataset.section = sectionId;

    var groupHeader = document.createElement('div');
    groupHeader.className = 'completed-group-header';

    var groupToggle = document.createElement('button');
    groupToggle.type = 'button';
    groupToggle.className = 'completed-group-toggle';
    groupToggle.setAttribute('aria-expanded', 'true');

    var groupArrow = document.createElement('span');
    groupArrow.className = 'completed-group-arrow';
    groupArrow.innerHTML = '&#9660;';
    groupArrow.setAttribute('aria-hidden', 'true');

    var groupLabel = document.createElement('span');
    groupLabel.className = 'completed-group-label';
    groupLabel.textContent = sectionLabelMap[sectionId] || sectionId;

    groupToggle.appendChild(groupArrow);
    groupToggle.appendChild(groupLabel);
    groupHeader.appendChild(groupToggle);

    var list = document.createElement('ol');
    list.className = 'tasks';
    list.id = 'completed-group-' + sectionId;
    groupToggle.setAttribute('aria-controls', list.id);
    attachTaskReorder(list);

    groupToggle.addEventListener('click', function () {
      var collapsed = groupHeader.classList.toggle('collapsed');
      list.classList.toggle('collapsed', collapsed);
      groupToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });

    group.appendChild(groupHeader);
    group.appendChild(list);
    completedBody.appendChild(group);

    completedGroupMap[sectionId] = list;
    return list;
  }

  function removeCompletedGroupIfEmpty(sectionId) {
    var list = completedGroupMap[sectionId];
    if (list && list.children.length === 0) {
      var group = list.closest('.completed-group');
      if (group) {
        group.remove();
      }
      delete completedGroupMap[sectionId];
    }
  }

  function moveToCompleted(li, sectionId) {
    li.classList.add('done');
    var destination = ensureCompletedGroup(sectionId);
    destination.appendChild(li);
    renumber(sectionListMap[sectionId]);
    renumber(destination);
    updateSectionCount(sectionId);
    updateCompletedCount();
  }

  function moveToActive(li, sectionId) {
    li.classList.remove('done');
    var destination = sectionListMap[sectionId];
    destination.appendChild(li);
    renumber(destination);

    var completedList = completedGroupMap[sectionId];
    if (completedList) {
      renumber(completedList);
      removeCompletedGroupIfEmpty(sectionId);
    }

    updateSectionCount(sectionId);
    updateCompletedCount();
  }

  function deleteTask(li, taskId, sectionId) {
    if (!taskId) {
      li.remove();
      return;
    }

    li.classList.add('deleting');

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
        var wasInCompleted = completedBody.contains(li);
        var list = li.closest('ol.tasks');
        li.remove();

        if (list) {
          renumber(list);
        }

        if (wasInCompleted) {
          removeCompletedGroupIfEmpty(sectionId);
          updateCompletedCount();
        } else {
          updateSectionCount(sectionId);
        }

        showSaveStatus('Task deleted', false);
      })
      .catch(function (err) {
        li.classList.remove('deleting');
        showSaveStatus(err.message, true);
      });
  }

  function buildSection(sectionData) {
    sectionLabelMap[sectionData.id] = sectionData.label;

    var section = document.createElement('div');
    section.className = 'section';
    section.dataset.id = sectionData.id;

    var header = document.createElement('div');
    header.className = 'section-header';
    header.draggable = true;

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'section-toggle';
    toggle.setAttribute('aria-expanded', 'true');
    toggle.setAttribute('aria-controls', sectionData.id);

    var arrow = document.createElement('span');
    arrow.className = 'section-arrow';
    arrow.innerHTML = '&#9660;';
    arrow.setAttribute('aria-hidden', 'true');

    var label = document.createElement('span');
    label.className = 'section-label';
    label.textContent = sectionData.label;

    var count = document.createElement('span');
    count.className = 'section-count';
    count.id = 'count-' + sectionData.id;

    toggle.appendChild(arrow);
    toggle.appendChild(label);
    toggle.appendChild(count);
    header.appendChild(toggle);

    var reorderControls = document.createElement('span');
    reorderControls.className = 'section-reorder-controls';

    var moveUpBtn = document.createElement('button');
    moveUpBtn.type = 'button';
    moveUpBtn.className = 'section-move-btn section-move-up';
    moveUpBtn.setAttribute('aria-label', 'Move ' + sectionData.label + ' section up');
    moveUpBtn.textContent = '↑';

    var moveDownBtn = document.createElement('button');
    moveDownBtn.type = 'button';
    moveDownBtn.className = 'section-move-btn section-move-down';
    moveDownBtn.setAttribute('aria-label', 'Move ' + sectionData.label + ' section down');
    moveDownBtn.textContent = '↓';

    reorderControls.appendChild(moveUpBtn);
    reorderControls.appendChild(moveDownBtn);
    header.appendChild(reorderControls);

    section.appendChild(header);

    if (sectionData.note) {
      var sectionNote = document.createElement('div');
      sectionNote.className = 'section-note';
      sectionNote.textContent = sectionData.note;
      section.appendChild(sectionNote);
    }

    var list = document.createElement('ol');
    list.className = 'tasks';
    list.id = sectionData.id;
    attachTaskReorder(list);
    sectionListMap[sectionData.id] = list;
    section.appendChild(list);

    sectionData.tasks.forEach(function (taskData) {
      var task = buildTask(taskData, sectionData.id);
      if (taskData.done) {
        ensureCompletedGroup(sectionData.id).appendChild(task);
      } else {
        list.appendChild(task);
      }
    });

    if (!getFilterSlugFromPath() && activeTaskView === 'all') {
      header.classList.add('collapsed');
      list.classList.add('collapsed');
      toggle.setAttribute('aria-expanded', 'false');
    }

    // A drag gesture that starts and ends on the header can, in some
    // browsers, still fire a click on release - without this guard that
    // click would immediately re-toggle the section a drag just opened
    // or closed.
    var sectionJustDragged = false;

    toggle.addEventListener('click', function () {
      if (sectionJustDragged) {
        return;
      }
      var collapsed = header.classList.toggle('collapsed');
      list.classList.toggle('collapsed', collapsed);
      toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });

    header.addEventListener('dragstart', function (e) {
      section.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', sectionData.id);
    });

    header.addEventListener('dragend', function () {
      section.classList.remove('dragging');
      sectionJustDragged = true;
      setTimeout(function () { sectionJustDragged = false; }, 0);
      updateSectionMoveButtons();
    });

    moveUpBtn.addEventListener('click', function () { moveSection(section, -1); });
    moveDownBtn.addEventListener('click', function () { moveSection(section, 1); });

    return section;
  }

  function getDragAfterElement(container, y) {
    var elements = Array.prototype.slice.call(
      container.querySelectorAll('.section:not(.dragging)')
    );
    return elements.reduce(function (closest, child) {
      var box = child.getBoundingClientRect();
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset: offset, element: child };
      }
      return closest;
    }, { offset: -Infinity, element: null }).element;
  }

  sectionsContainer.addEventListener('dragover', function (e) {
    e.preventDefault();
    var dragging = sectionsContainer.querySelector('.section.dragging');
    if (!dragging) {
      return;
    }
    var afterElement = getDragAfterElement(sectionsContainer, e.clientY);
    if (afterElement == null) {
      sectionsContainer.appendChild(dragging);
    } else {
      sectionsContainer.insertBefore(dragging, afterElement);
    }
  });

  // Keyboard-only equivalent of dragging a section header: swaps it with
  // the sibling in `direction` (-1 up, 1 down) so the same DOM order the
  // drag path produces is reachable without a pointer.
  function moveSection(sectionEl, direction) {
    var sibling = direction < 0 ? sectionEl.previousElementSibling : sectionEl.nextElementSibling;
    if (!sibling) {
      return;
    }
    if (direction < 0) {
      sectionsContainer.insertBefore(sectionEl, sibling);
    } else {
      sectionsContainer.insertBefore(sibling, sectionEl);
    }
    updateSectionMoveButtons();
  }

  function updateSectionMoveButtons() {
    var sections = sectionsContainer.children;
    var total = sections.length;
    Array.prototype.forEach.call(sections, function (sectionEl, index) {
      var upBtn = sectionEl.querySelector(':scope > .section-header > .section-reorder-controls > .section-move-up');
      var downBtn = sectionEl.querySelector(':scope > .section-header > .section-reorder-controls > .section-move-down');
      if (upBtn) { upBtn.disabled = index === 0; }
      if (downBtn) { downBtn.disabled = index === total - 1; }
    });
  }

  function renumber(list) {
    var total = list.children.length;
    Array.prototype.forEach.call(list.children, function (task, index) {
      var num = task.querySelector('.num');
      num.textContent = String(index + 1).padStart(2, '0');
      var upBtn = task.querySelector(':scope > .task-reorder-controls > .task-move-up');
      var downBtn = task.querySelector(':scope > .task-reorder-controls > .task-move-down');
      if (upBtn) { upBtn.disabled = index === 0; }
      if (downBtn) { downBtn.disabled = index === total - 1; }
    });
  }

  function updateSectionCount(sectionId) {
    var el = document.getElementById('count-' + sectionId);
    if (!el) {
      return;
    }
    var total = sectionListMap[sectionId].children.length;
    el.textContent = total + ' open';
  }

  function updateCompletedCount() {
    var total = completedBody.querySelectorAll('.task').length;
    completedCountEl.textContent = total;
  }

  function buildCompletedFilterBar(sections) {
    if (!completedFilterBar) {
      return;
    }
    completedFilterBar.innerHTML = '';

    var allPill = document.createElement('button');
    allPill.type = 'button';
    allPill.className = 'completed-filter-pill' + (completedCategoryFilter === 'all' ? ' active' : '');
    allPill.dataset.filter = 'all';
    allPill.textContent = 'All';
    completedFilterBar.appendChild(allPill);

    sections.forEach(function (sectionData) {
      var pill = document.createElement('button');
      pill.type = 'button';
      pill.className = 'completed-filter-pill' + (completedCategoryFilter === sectionData.id ? ' active' : '');
      pill.dataset.filter = sectionData.id;
      pill.textContent = sectionData.label;
      completedFilterBar.appendChild(pill);
    });

    completedFilterBar.querySelectorAll('.completed-filter-pill').forEach(function (pill) {
      pill.addEventListener('click', function () {
        completedCategoryFilter = pill.dataset.filter;
        completedFilterBar.querySelectorAll('.completed-filter-pill').forEach(function (p) {
          p.classList.toggle('active', p === pill);
        });
        applySearchFilter();
      });
    });
  }

  var scratchpadInput = document.getElementById('scratchpad-input');
  var scratchpadStatusEl = document.getElementById('scratchpad-status');
  var scratchpadDateEl = document.getElementById('scratchpad-date');
  var scratchpadPrevBtn = document.getElementById('scratchpad-prev-day');
  var scratchpadNextBtn = document.getElementById('scratchpad-next-day');
  var scratchpadTodayBtn = document.getElementById('scratchpad-today-btn');
  var scratchpadCarryForwardBtn = document.getElementById('scratchpad-carry-forward-btn');
  var scratchpadConvertSection = document.getElementById('scratchpad-convert-section');
  var scratchpadConvertBtn = document.getElementById('scratchpad-convert-btn');
  var scratchpadConvertConfirmEl = document.getElementById('scratchpad-convert-confirm');
  var scratchpadSaveTimer = null;
  var scratchpadLastSaved = '';
  // The day currently loaded in the textarea - never advances on its own
  // (e.g. at midnight): it only changes via explicit navigation, so a save
  // in flight always lands on the day the user was actually looking at.
  var scratchpadViewDate = getLocalDateString();
  var SCRATCHPAD_LAST_SECTION_KEY = 'scratchpad-convert-section';

  // "THU SEP 10" - the sidebar's date heading, for whichever day is loaded.
  function formatScratchpadHeaderDate(dateString) {
    var parts = dateString.split('-').map(Number);
    var d = new Date(parts[0], parts[1] - 1, parts[2]);
    return DAY_NAMES[d.getDay()] + ' ' + MONTH_NAMES[d.getMonth()] + ' ' + d.getDate();
  }

  function renderScratchpadNav() {
    if (scratchpadDateEl) {
      scratchpadDateEl.textContent = formatScratchpadHeaderDate(scratchpadViewDate);
    }
    if (scratchpadPrevBtn) {
      scratchpadPrevBtn.textContent = '‹ ' + formatShortDate(addDaysToDateString(scratchpadViewDate, -1));
      scratchpadPrevBtn.setAttribute('aria-label', 'Go to ' + formatShortDate(addDaysToDateString(scratchpadViewDate, -1)));
    }
    if (scratchpadNextBtn) {
      scratchpadNextBtn.textContent = formatShortDate(addDaysToDateString(scratchpadViewDate, 1)) + ' ›';
      scratchpadNextBtn.setAttribute('aria-label', 'Go to ' + formatShortDate(addDaysToDateString(scratchpadViewDate, 1)));
    }
    if (scratchpadTodayBtn) {
      scratchpadTodayBtn.disabled = (scratchpadViewDate === getLocalDateString());
    }
  }

  // Persistent, not a flash: it stays until the next state change so it can
  // be trusted at a glance, rather than fading on a timer regardless of
  // whether the save actually succeeded.
  function showScratchpadStatus(text, isError) {
    if (!scratchpadStatusEl) {
      return;
    }
    scratchpadStatusEl.textContent = text;
    scratchpadStatusEl.classList.toggle('error', !!isError);
    scratchpadStatusEl.classList.add('show');
  }

  function isScratchpadDirty() {
    return scratchpadInput.value !== scratchpadLastSaved;
  }

  function saveScratchpad(useBeacon) {
    if (scratchpadSaveTimer) {
      clearTimeout(scratchpadSaveTimer);
      scratchpadSaveTimer = null;
    }

    var text = scratchpadInput.value;
    if (text === scratchpadLastSaved) {
      return;
    }

    var entryDate = scratchpadViewDate;

    if (useBeacon && navigator.sendBeacon) {
      var blob = new Blob([JSON.stringify({ date: entryDate, text: text })], { type: 'application/json' });
      if (navigator.sendBeacon('/tasks/scratchpad', blob)) {
        scratchpadLastSaved = text;
        return;
      }
      // sendBeacon declined to queue the request (e.g. payload too large) -
      // fall through to a normal fetch, best-effort during unload.
    }

    showScratchpadStatus('Saving...', false);
    fetch('/tasks/scratchpad', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: entryDate, text: text })
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Save failed (status ' + response.status + ')');
        }
        return response.json();
      })
      .then(function () {
        scratchpadLastSaved = text;
        showScratchpadStatus('Saved', false);
      })
      .catch(function (err) {
        showScratchpadStatus(err.message, true);
      });
  }

  // Loads another day's entry into the textarea without touching the task
  // list - a dedicated endpoint (GET /tasks/scratchpad.json) rather than
  // re-fetching and re-rendering all of /tasks.json just to flip a day.
  function fetchScratchpadDay(dateString) {
    showScratchpadStatus('Loading...', false);
    fetch('/tasks/scratchpad.json?date=' + encodeURIComponent(dateString))
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Could not load that day (status ' + response.status + ')');
        }
        return response.json();
      })
      .then(function (data) {
        // The user navigated again before this resolved - drop the now-stale response.
        if (dateString !== scratchpadViewDate) {
          return;
        }
        scratchpadInput.value = data.text || '';
        scratchpadLastSaved = data.text || '';
        showScratchpadStatus('Saved', false);
      })
      .catch(function (err) {
        showScratchpadStatus(err.message, true);
      });
  }

  function goToScratchpadDay(newDate) {
    if (newDate === scratchpadViewDate) {
      return;
    }
    // Flush the outgoing day's edits before navigating, so the last
    // keystrokes on it are never lost.
    if (isScratchpadDirty()) {
      saveScratchpad(false);
    }
    scratchpadViewDate = newDate;
    renderScratchpadNav();
    fetchScratchpadDay(newDate);
    if (scratchpadConvertConfirmEl) {
      scratchpadConvertConfirmEl.hidden = true;
    }
  }

  if (scratchpadPrevBtn) {
    scratchpadPrevBtn.addEventListener('click', function () {
      goToScratchpadDay(addDaysToDateString(scratchpadViewDate, -1));
    });
  }
  if (scratchpadNextBtn) {
    scratchpadNextBtn.addEventListener('click', function () {
      goToScratchpadDay(addDaysToDateString(scratchpadViewDate, 1));
    });
  }
  if (scratchpadTodayBtn) {
    scratchpadTodayBtn.addEventListener('click', function () {
      goToScratchpadDay(getLocalDateString());
    });
  }

  // Non-blank lines from the previous day that aren't already present
  // (exact match) get appended - never automatic, and safe to press twice
  // since the second pass finds them already there.
  if (scratchpadCarryForwardBtn) {
    scratchpadCarryForwardBtn.addEventListener('click', function () {
      var previousDate = addDaysToDateString(scratchpadViewDate, -1);
      fetch('/tasks/scratchpad.json?date=' + encodeURIComponent(previousDate))
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Could not load the previous day (status ' + response.status + ')');
          }
          return response.json();
        })
        .then(function (data) {
          var previousLines = (data.text || '').split('\n').filter(function (line) {
            return line.trim() !== '';
          });
          var currentLines = scratchpadInput.value.split('\n');
          var toAdd = previousLines.filter(function (line) {
            return currentLines.indexOf(line) === -1;
          });
          if (toAdd.length === 0) {
            showScratchpadStatus('Nothing to carry forward', false);
            return;
          }
          var current = scratchpadInput.value;
          var separator = current && !current.endsWith('\n') ? '\n' : '';
          scratchpadInput.value = current + separator + toAdd.join('\n');
          saveScratchpad(false);
        })
        .catch(function (err) {
          showScratchpadStatus(err.message, true);
        });
    });
  }

  // The selected text, or the line the caret is in when nothing is
  // selected - for "convert this line to a task".
  function getScratchpadConvertCandidate() {
    var start = scratchpadInput.selectionStart;
    var end = scratchpadInput.selectionEnd;
    if (start !== end) {
      return scratchpadInput.value.slice(start, end);
    }
    var value = scratchpadInput.value;
    var lineStart = value.lastIndexOf('\n', start - 1) + 1;
    var lineEnd = value.indexOf('\n', start);
    if (lineEnd === -1) {
      lineEnd = value.length;
    }
    return value.slice(lineStart, lineEnd);
  }

  function populateScratchpadConvertSections(sections) {
    if (!scratchpadConvertSection) {
      return;
    }
    var lastUsed = localStorage.getItem(SCRATCHPAD_LAST_SECTION_KEY);
    scratchpadConvertSection.innerHTML = '';
    sections.forEach(function (section) {
      var option = document.createElement('option');
      option.value = section.id;
      option.textContent = section.label;
      scratchpadConvertSection.appendChild(option);
    });
    if (lastUsed && sections.some(function (s) { return s.id === lastUsed; })) {
      scratchpadConvertSection.value = lastUsed;
    }
  }

  if (scratchpadConvertBtn) {
    scratchpadConvertBtn.addEventListener('click', function () {
      var text = getScratchpadConvertCandidate().trim();
      var sectionId = scratchpadConvertSection ? scratchpadConvertSection.value : '';
      if (!text || !sectionId) {
        return;
      }

      scratchpadConvertBtn.disabled = true;
      fetch('/tasks/quick-task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section_id: sectionId, desc: text })
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Could not create the task (status ' + response.status + ')');
          }
          return response.json();
        })
        .then(function (data) {
          localStorage.setItem(SCRATCHPAD_LAST_SECTION_KEY, sectionId);
          if (scratchpadConvertConfirmEl) {
            scratchpadConvertConfirmEl.innerHTML = 'Created <a href="/task/' +
              encodeURIComponent(data.id) + '">' + text.replace(/[&<>]/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
              }) + '</a>';
            scratchpadConvertConfirmEl.hidden = false;
          }
        })
        .catch(function (err) {
          showScratchpadStatus(err.message, true);
        })
        .finally(function () {
          scratchpadConvertBtn.disabled = false;
        });
    });
  }

  if (scratchpadInput) {
    scratchpadInput.addEventListener('input', function () {
      showScratchpadStatus('Unsaved changes', false);
      if (scratchpadSaveTimer) {
        clearTimeout(scratchpadSaveTimer);
      }
      scratchpadSaveTimer = setTimeout(function () { saveScratchpad(false); }, 800);
    });

    // The debounce alone loses keystrokes typed in the 800ms before a
    // navigation or tab close - flush immediately on every point where the
    // page might go away.
    scratchpadInput.addEventListener('blur', function () { saveScratchpad(false); });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') {
        saveScratchpad(true);
      }
    });
    window.addEventListener('pagehide', function () { saveScratchpad(true); });
  }

  function render(data) {
    if (scratchpadInput) {
      var scratchpadText = (data.scratchpad && data.scratchpad.text) || '';
      scratchpadViewDate = (data.scratchpad && data.scratchpad.date) || getLocalDateString();
      scratchpadInput.value = scratchpadText;
      scratchpadLastSaved = scratchpadText;
      renderScratchpadNav();
      populateScratchpadConvertSections(data.sections);
    }

    taskById = {};
    data.sections.forEach(function (sectionData) {
      (sectionData.tasks || []).forEach(function (taskData) {
        if (taskData.id) {
          taskById[taskData.id] = taskData;
        }
      });
    });

    var filterSlug = getFilterSlugFromPath();
    var sectionsToRender = data.sections;
    var matchedSection = null;

    if (filterSlug) {
      matchedSection = data.sections.filter(function (s) {
        return s.slug === filterSlug;
      })[0] || null;
      sectionsToRender = matchedSection ? [matchedSection] : [];
    }

    applyFilteredHeader(matchedSection, filterSlug);

    if (filterSlug && !matchedSection) {
      var notFound = document.createElement('p');
      notFound.textContent = 'No task category matches this URL.';
      sectionsContainer.appendChild(notFound);
    }

    sectionsToRender.forEach(function (sectionData) {
      sectionsContainer.appendChild(buildSection(sectionData));
    });
    updateSectionMoveButtons();

    if (data.footnote && !filterSlug) {
      footnoteEl.innerHTML = data.footnote;
      footnoteEl.style.display = '';
    } else {
      footnoteEl.style.display = 'none';
    }

    Object.keys(sectionListMap).forEach(function (id) {
      renumber(sectionListMap[id]);
      updateSectionCount(id);
    });
    Object.keys(completedGroupMap).forEach(function (id) {
      renumber(completedGroupMap[id]);
    });
    document.querySelectorAll('ol.tasks').forEach(function (list) {
      Array.prototype.forEach.call(list.children, function (task, index) {
        task.dataset.personalOrder = String(index);
      });
    });
    updateCompletedCount();
    buildCompletedFilterBar(sectionsToRender);
    updateViewCounts();

    // Completed panel starts collapsed.
    setCompletedExpanded(false);

    renderTaskControls();
    sortTaskLists();
    applySearchFilter();
  }

  function getFilterSlugFromPath() {
    var match = window.location.pathname.match(/^\/tasks\/([a-z0-9-]+)$/);
    if (!match || match[1] === 'new') {
      return null;
    }
    return match[1];
  }

  function applyFilteredHeader(matchedSection, filterSlug) {
    var titleEl = document.getElementById('page-title');
    var metaEl = document.getElementById('page-meta');
    var ctaEl = document.getElementById('new-task-cta');

    if (!filterSlug) {
      return;
    }

    if (titleEl) {
      titleEl.textContent = matchedSection ? matchedSection.label : 'Unknown category';
      document.title = (matchedSection ? matchedSection.label : 'Unknown category') + ' - Personal Tasks';
    }

    if (metaEl) {
      metaEl.innerHTML = '<a class="back-link" href="/tasks/categories">&larr; All categories</a>';
    }

    if (ctaEl && matchedSection) {
      ctaEl.href = '/tasks/new?section=' + encodeURIComponent(matchedSection.id);
    }
  }

  function setCompletedExpanded(expanded) {
    completedHeader.classList.toggle('collapsed', !expanded);
    completedBody.classList.toggle('collapsed', !expanded);
    if (completedFilterBar) {
      completedFilterBar.classList.toggle('collapsed', !expanded);
    }
    if (completedToggle) {
      completedToggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }
  }

  if (completedToggle) {
    completedToggle.addEventListener('click', function () {
      setCompletedExpanded(completedHeader.classList.contains('collapsed'));
    });
  }

  var searchInput = document.getElementById('task-search');

  function taskMatchesQuery(li, query) {
    var desc = li.querySelector('.desc');
    var note = li.querySelector('.note');
    var text = (desc ? desc.textContent : '') + ' ' + (note ? note.textContent : '');
    li.querySelectorAll('.tag').forEach(function (tag) {
      text += ' ' + tag.textContent;
    });
    return text.toLowerCase().indexOf(query) !== -1;
  }

  function groupHasVisibleTask(list) {
    return list ? Array.prototype.some.call(list.children, function (li) {
      return !li.classList.contains('search-hidden');
    }) : false;
  }

  function ticketTypeFor(ticketNumber) {
    var match = (ticketNumber || '').match(/^[A-Za-z]+/);
    return match ? match[0].toUpperCase() : '';
  }

  function currentTaskUrl() {
    var url = new URL(window.location.href);
    TASK_FACETS.forEach(function (facet) { url.searchParams.delete(facet); });
    if (activeTaskView === 'all') {
      url.searchParams.delete('view');
    } else {
      url.searchParams.set('view', activeTaskView);
    }
    if (activeTaskSort === 'personal') {
      url.searchParams.delete('sort');
    } else {
      url.searchParams.set('sort', activeTaskSort);
    }
    TASK_FACETS.forEach(function (facet) {
      activeTaskFilters[facet].forEach(function (value) { url.searchParams.append(facet, value); });
    });
    return url;
  }

  function writeTaskUrl() {
    var url = currentTaskUrl();
    window.history.pushState({}, '', url.pathname + url.search);
  }

  function matchesFacet(li, facet) {
    var values = activeTaskFilters[facet];
    if (!values.length) {
      return true;
    }
    var datasetKey = facet.replace(/_([a-z])/g, function (_, letter) { return letter.toUpperCase(); });
    return values.indexOf(li.dataset[datasetKey] || '') !== -1;
  }

  function taskMatchesActiveFilters(li) {
    return TASK_FACETS.every(function (facet) { return matchesFacet(li, facet); });
  }

  function activeFilterLabels() {
    var labels = [];
    var viewLabels = { today: 'Today', waiting: 'Waiting', overdue: 'Overdue', 'no-due-date': 'No due date' };
    if (activeTaskView !== 'all') {
      labels.push(viewLabels[activeTaskView]);
    }
    if (searchInput && searchInput.value.trim()) {
      labels.push('search');
    }
    TASK_FACETS.forEach(function (facet) {
      activeTaskFilters[facet].forEach(function (value) { labels.push(value); });
    });
    return labels;
  }

  function resetTaskFilters() {
    activeTaskView = 'all';
    activeTaskSort = 'personal';
    TASK_FACETS.forEach(function (facet) { activeTaskFilters[facet] = []; });
    if (searchInput) { searchInput.value = ''; }
    writeTaskUrl();
    renderTaskControls();
    sortTaskLists();
    applySearchFilter();
  }

  function applySearchFilter() {
    var query = searchInput ? searchInput.value.trim().toLowerCase() : '';
    var localToday = getLocalDateString();

    document.querySelectorAll('.task').forEach(function (li) {
      var matchesSearch = !query || taskMatchesQuery(li, query);
      var inCompleted = completedBody.contains(li);
      var matchesCategory = !inCompleted || completedCategoryFilter === 'all' ||
        li.dataset.section === completedCategoryFilter;
      var matchesView = activeTaskView === 'all' ||
        (activeTaskView === 'today' && (li.dataset.focusToday === 'true' || li.dataset.dueDate === localToday || li.dataset.status === 'in-progress')) ||
        (activeTaskView === 'waiting' && li.dataset.status === 'pending') ||
        (activeTaskView === 'overdue' && li.dataset.dueDate && li.dataset.dueDate < localToday && !inCompleted) ||
        (activeTaskView === 'no-due-date' && !li.dataset.dueDate && !inCompleted);
      li.classList.toggle('search-hidden', !(matchesSearch && matchesCategory && matchesView && taskMatchesActiveFilters(li)));
    });

    document.querySelectorAll('.section').forEach(function (section) {
      var list = section.querySelector('ol.tasks');
      section.classList.toggle('search-hidden', !groupHasVisibleTask(list));
    });

    document.querySelectorAll('.completed-group').forEach(function (group) {
      var list = group.querySelector('ol.tasks');
      group.classList.toggle('search-hidden', !groupHasVisibleTask(list));
    });

    if (taskViewEmpty) {
      var visibleActiveTasks = sectionsContainer.querySelectorAll('.task:not(.search-hidden)').length;
      var labels = activeFilterLabels();
      taskViewEmpty.hidden = visibleActiveTasks > 0;
      taskViewEmpty.replaceChildren();
      if (!visibleActiveTasks) {
        taskViewEmpty.append('No active tasks match ' + (labels.length ? labels.join(', ') : 'this view') + '. Your tasks are safe. ');
        var resetButton = document.createElement('button');
        resetButton.type = 'button';
        resetButton.className = 'task-filter-reset';
        resetButton.textContent = 'Reset filters';
        resetButton.addEventListener('click', resetTaskFilters);
        taskViewEmpty.appendChild(resetButton);
      }
    }
  }

  function updateViewCounts() {
    var localToday = getLocalDateString();
    var activeTasks = Array.prototype.slice.call(sectionsContainer.querySelectorAll('.task'));
    var counts = {
      today: activeTasks.filter(function (li) { return li.dataset.focusToday === 'true' || li.dataset.dueDate === localToday || li.dataset.status === 'in-progress'; }).length,
      waiting: activeTasks.filter(function (li) { return li.dataset.status === 'pending'; }).length,
      overdue: activeTasks.filter(function (li) { return li.dataset.dueDate && li.dataset.dueDate < localToday; }).length
    };
    Object.keys(counts).forEach(function (view) {
      var el = document.getElementById(view + '-count');
      if (el) { el.textContent = counts[view]; }
    });
  }

  function sortValue(li, field) {
    if (field === 'due-date') { return li.dataset.dueDate || '9999-12-31'; }
    if (field === 'recently-updated') { return li.dataset.modified || ''; }
    if (field === 'oldest-opened') { return li.dataset.sourceOpenedAt || li.dataset.created || '9999-12-31T23:59:59Z'; }
    if (field === 'priority') { return { high: '1', medium: '2', low: '3' }[li.dataset.priority] || '4'; }
    return li.dataset.personalOrder || '';
  }

  function sortTaskLists() {
    document.querySelectorAll('ol.tasks').forEach(function (list) {
      var tasks = Array.prototype.slice.call(list.children);
      tasks.sort(function (left, right) {
        var comparison = sortValue(left, activeTaskSort).localeCompare(sortValue(right, activeTaskSort));
        if (activeTaskSort === 'recently-updated') { comparison *= -1; }
        return comparison || Number(left.dataset.personalOrder) - Number(right.dataset.personalOrder);
      });
      tasks.forEach(function (task) { list.appendChild(task); });
      renumber(list);
    });
  }

  function addFacetGroup(label, facet, values, labels) {
    if (!values.length) { return; }
    var group = document.createElement('div');
    group.className = 'task-facet-group';
    var heading = document.createElement('span');
    heading.className = 'task-facet-label';
    heading.textContent = label;
    group.appendChild(heading);
    values.forEach(function (value) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'task-facet-chip';
      button.textContent = labels && labels[value] ? labels[value] : value;
      button.setAttribute('aria-pressed', activeTaskFilters[facet].indexOf(value) !== -1 ? 'true' : 'false');
      button.addEventListener('click', function () {
        var index = activeTaskFilters[facet].indexOf(value);
        if (index === -1) { activeTaskFilters[facet].push(value); } else { activeTaskFilters[facet].splice(index, 1); }
        writeTaskUrl();
        renderTaskControls();
        applySearchFilter();
      });
      group.appendChild(button);
    });
    taskFacetBar.appendChild(group);
  }

  function renderTaskControls() {
    if (taskViewBar) {
      if (!['all', 'today', 'waiting', 'overdue', 'no-due-date'].includes(activeTaskView)) { activeTaskView = 'all'; }
      taskViewBar.querySelectorAll('.task-view-pill').forEach(function (pill) {
        pill.classList.toggle('active', pill.dataset.view === activeTaskView);
        pill.setAttribute('aria-pressed', pill.dataset.view === activeTaskView ? 'true' : 'false');
        pill.onclick = function () {
          activeTaskView = pill.dataset.view;
          writeTaskUrl();
          renderTaskControls();
          applySearchFilter();
        };
      });
    }
    if (!taskFacetBar) { return; }
    taskFacetBar.replaceChildren();
    var tasks = Array.prototype.slice.call(document.querySelectorAll('.task'));
    addFacetGroup('Status', 'status', ['open', 'in-progress', 'pending'], {
      open: 'Open', 'in-progress': 'In progress', pending: 'Waiting'
    });
    addFacetGroup('Priority', 'priority', ['high', 'medium', 'low'], PRIORITY_LABELS);
    addFacetGroup('Ticket type', 'ticket_type', Array.from(new Set(tasks.map(function (li) { return li.dataset.ticketType; }).filter(Boolean))).sort());
    addFacetGroup('Assignment group', 'assignment_group', Array.from(new Set(tasks.map(function (li) { return li.dataset.assignmentGroup; }).filter(Boolean))).sort());
    addFacetGroup('Origin', 'origin', ['local'], { local: 'Locally created' });
    addFacetGroup('Freshness', 'freshness', ['changed'], { changed: 'Changed since last sync' });

    var sortGroup = document.createElement('label');
    sortGroup.className = 'task-sort-control';
    sortGroup.textContent = 'Sort';
    var sortSelect = document.createElement('select');
    [['personal', 'Personal order'], ['due-date', 'Due date (undated last)'], ['recently-updated', 'Recently updated'], ['oldest-opened', 'Oldest opened'], ['priority', 'Priority']].forEach(function (entry) {
      var option = document.createElement('option');
      option.value = entry[0];
      option.textContent = entry[1];
      option.selected = entry[0] === activeTaskSort;
      sortSelect.appendChild(option);
    });
    sortSelect.addEventListener('change', function () {
      activeTaskSort = sortSelect.value;
      writeTaskUrl();
      sortTaskLists();
    });
    sortGroup.appendChild(sortSelect);
    taskFacetBar.appendChild(sortGroup);
  }

  window.addEventListener('popstate', function () {
    var params = new URLSearchParams(window.location.search);
    activeTaskView = params.get('view') || 'all';
    activeTaskSort = params.get('sort') || 'personal';
    TASK_FACETS.forEach(function (facet) { activeTaskFilters[facet] = params.getAll(facet); });
    renderTaskControls();
    sortTaskLists();
    applySearchFilter();
  });

  if (searchInput) {
    searchInput.addEventListener('input', applySearchFilter);
  }

  var addedBanner = document.getElementById('added-banner');
  if (addedBanner && /[?&]added=1\b/.test(window.location.search)) {
    addedBanner.classList.add('show');
    var cleanUrl = window.location.pathname;
    window.history.replaceState({}, document.title, cleanUrl);
  }

  var saveButton = document.getElementById('save-changes-btn');
  var saveStatusEl = document.getElementById('save-status');
  var saveStatusTimer = null;

  function showSaveStatus(text, isError) {
    if (!saveStatusEl) {
      return;
    }
    saveStatusEl.textContent = text;
    saveStatusEl.classList.toggle('error', !!isError);
    saveStatusEl.classList.add('show');
    if (saveStatusTimer) {
      clearTimeout(saveStatusTimer);
    }
    saveStatusTimer = setTimeout(function () {
      saveStatusEl.classList.remove('show');
    }, 2500);
  }

  function collectUpdates() {
    var updates = [];
    document.querySelectorAll('.task').forEach(function (li) {
      var taskId = li.dataset.taskId;
      if (!taskId) {
        return;
      }
      var textarea = li.querySelector('.notes-input');
      var dueInput = li.querySelector('.due-date-input');
      var estimateInput = li.querySelector('.time-estimate-input');
      var todayInput = li.querySelector('.focus-today-input');
      var followUpInput = li.querySelector('.follow-up-date-input');
      var update = {
        id: taskId,
        notes: textarea ? textarea.value : '',
        status: li.dataset.status || 'open',
        priority: li.dataset.priority || 'medium',
        due_date: dueInput ? dueInput.value : '',
        focus_today: todayInput ? todayInput.checked : false,
        follow_up_date: followUpInput ? followUpInput.value : '',
        time_estimate: estimateInput ? estimateInput.value : ''
      };
      ENVIRONMENTS.forEach(function (env) {
        var envInput = li.querySelector('.env-' + env + '-input');
        if (envInput) {
          update['env_' + env] = envInput.checked;
        }
      });
      var cmdbInput = li.querySelector('.cmdb-updated-input');
      if (cmdbInput) {
        update.cmdb_updated = cmdbInput.checked;
      }
      updates.push(update);
    });
    return updates;
  }

  if (saveButton) {
    saveButton.addEventListener('click', function () {
      saveButton.disabled = true;
      fetch('/tasks/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectUpdates())
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Save failed (status ' + response.status + ')');
          }
          return response.json();
        })
        .then(function () {
          showSaveStatus('Saved', false);
        })
        .catch(function (err) {
          showSaveStatus(err.message, true);
        })
        .finally(function () {
          saveButton.disabled = false;
        });
    });
  }

  Promise.all([
    fetch('/tasks.json?scratchpad_date=' + encodeURIComponent(getLocalDateString())).then(function (response) {
      if (!response.ok) {
        throw new Error('Could not load tasks.json (status ' + response.status + ')');
      }
      return response.json();
    }),
    fetch('/tasks/sync-status.json').then(function (response) {
      if (!response.ok) {
        throw new Error('Could not load sync status (status ' + response.status + ')');
      }
      return response.json();
    })
  ])
    .then(function (responses) {
      previousSuccessfulSyncStartedAt = responses[1].previous_success_started_at || '';
      render(responses[0]);
      renderSyncHealth(responses[1]);
    })
    .catch(function (err) {
      sectionsContainer.textContent = 'Failed to load tasks: ' + err.message +
        '. If you opened this file directly, run a local server instead (see README.md).';
    });
})();
