(function () {
  'use strict';

  var sectionsContainer = document.getElementById('sections');
  var footnoteEl = document.getElementById('footnote-text');
  var completedHeader = document.getElementById('completed-header');
  var completedBody = document.getElementById('completed-body');
  var completedCountEl = document.getElementById('completed-count');
  var completedFilterBar = document.getElementById('completed-filter-bar');
  var completedCategoryFilter = 'all';

  var sectionListMap = {};    // sectionId -> main <ol> in the left column
  var sectionLabelMap = {};   // sectionId -> section label text
  var completedGroupMap = {}; // sectionId -> <ol> inside the completed panel
  var taskById = {};          // task id -> task data, for resolving parent_id

  var WORK_SECTION_ID = 'own-tasks';
  var ENVIRONMENTS = ['dev', 'qa', 'prod'];

  var DAY_NAMES = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  var MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

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

    var handle = document.createElement('span');
    handle.className = 'drag-handle';
    handle.setAttribute('draggable', 'true');
    handle.setAttribute('aria-hidden', 'true');
    handle.title = 'Drag to reorder';
    handle.textContent = '⋮⋮';

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

    var descRow = document.createElement('div');
    descRow.className = 'desc-row';

    var toggleArrow = document.createElement('span');
    toggleArrow.className = 'task-toggle-arrow';
    toggleArrow.innerHTML = '&#9660;';
    toggleArrow.setAttribute('aria-hidden', 'true');

    var desc = document.createElement('div');
    desc.className = 'desc';
    desc.textContent = taskData.desc;

    descRow.appendChild(toggleArrow);
    descRow.appendChild(desc);
    descRow.addEventListener('click', function () {
      li.classList.toggle('task-collapsed');
    });
    body.appendChild(descRow);

    var details = document.createElement('div');
    details.className = 'task-details';
    body.appendChild(details);

    if (taskData.note) {
      var note = document.createElement('div');
      note.className = 'note';
      note.textContent = taskData.note;
      details.appendChild(note);
    }

    var parentTask = taskData.parent_id ? taskById[taskData.parent_id] : null;

    var fieldEntries = [
      { key: 'ticket_number', label: '', className: 'ticket' },
      { key: 'assignment_group', label: '', className: 'group' },
      { key: 'requested_by', label: 'req: ', className: 'requester' },
      { key: 'related_files', label: 'files: ', className: 'files' },
      { key: 'parent_id', label: 'parent: ', className: 'parent', value: parentTask ? parentTask.desc : '' }
    ].filter(function (entry) {
      return entry.value !== undefined ? entry.value : taskData[entry.key];
    });

    if (fieldEntries.length > 0) {
      var fields = document.createElement('div');
      fields.className = 'task-fields';
      fieldEntries.forEach(function (entry) {
        var pill = document.createElement('span');
        pill.className = 'field-pill field-pill-' + entry.className;
        var value = entry.value !== undefined ? entry.value : taskData[entry.key];
        pill.textContent = entry.label + value;
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
    quickFields.appendChild(estimateField);
    details.appendChild(quickFields);

    var isWorkTask = sectionId === WORK_SECTION_ID;
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
    li.appendChild(num);
    li.appendChild(controls);
    li.appendChild(body);
    li.appendChild(deleteBtn);

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
    });

    statusSelect.addEventListener('change', function () {
      var newStatus = statusSelect.value;
      var wasInCompleted = completedBody.contains(li);

      li.dataset.status = newStatus;
      li.classList.toggle('in-progress', newStatus === 'in-progress');
      li.classList.toggle('pending', newStatus === 'pending');
      li.classList.toggle('cancelled', newStatus === 'cancelled');

      if (newStatus === 'done') {
        moveToCompleted(li, sectionId);
      } else if (wasInCompleted) {
        moveToActive(li, sectionId);
      } else {
        li.classList.remove('done');
        updateSectionCount(sectionId);
      }
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

    var groupArrow = document.createElement('span');
    groupArrow.className = 'completed-group-arrow';
    groupArrow.innerHTML = '&#9660;';

    var groupLabel = document.createElement('span');
    groupLabel.className = 'completed-group-label';
    groupLabel.textContent = sectionLabelMap[sectionId] || sectionId;

    groupHeader.appendChild(groupArrow);
    groupHeader.appendChild(groupLabel);

    var list = document.createElement('ol');
    list.className = 'tasks';
    attachTaskReorder(list);

    groupHeader.addEventListener('click', function () {
      groupHeader.classList.toggle('collapsed');
      list.classList.toggle('collapsed');
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

    var arrow = document.createElement('span');
    arrow.className = 'section-arrow';
    arrow.innerHTML = '&#9660;';

    var label = document.createElement('span');
    label.className = 'section-label';
    label.textContent = sectionData.label;

    var count = document.createElement('span');
    count.className = 'section-count';
    count.id = 'count-' + sectionData.id;

    header.appendChild(arrow);
    header.appendChild(label);
    header.appendChild(count);
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

    if (!getFilterSlugFromPath()) {
      header.classList.add('collapsed');
      list.classList.add('collapsed');
    }

    header.addEventListener('click', function () {
      header.classList.toggle('collapsed');
      list.classList.toggle('collapsed');
    });

    header.addEventListener('dragstart', function (e) {
      section.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', sectionData.id);
    });

    header.addEventListener('dragend', function () {
      section.classList.remove('dragging');
    });

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

  function renumber(list) {
    var n = 1;
    Array.prototype.forEach.call(list.children, function (task) {
      var num = task.querySelector('.num');
      num.textContent = String(n).padStart(2, '0');
      n += 1;
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

  function render(data) {
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
    updateCompletedCount();
    buildCompletedFilterBar(sectionsToRender);

    // Completed panel starts collapsed.
    completedHeader.classList.add('collapsed');
    completedBody.classList.add('collapsed');
    if (completedFilterBar) {
      completedFilterBar.classList.add('collapsed');
    }

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

  completedHeader.addEventListener('click', function () {
    completedHeader.classList.toggle('collapsed');
    completedBody.classList.toggle('collapsed');
    if (completedFilterBar) {
      completedFilterBar.classList.toggle('collapsed');
    }
  });

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

  function applySearchFilter() {
    var query = searchInput ? searchInput.value.trim().toLowerCase() : '';

    document.querySelectorAll('.task').forEach(function (li) {
      var matchesSearch = !query || taskMatchesQuery(li, query);
      var inCompleted = completedBody.contains(li);
      var matchesCategory = !inCompleted || completedCategoryFilter === 'all' ||
        li.dataset.section === completedCategoryFilter;
      li.classList.toggle('search-hidden', !(matchesSearch && matchesCategory));
    });

    document.querySelectorAll('.section').forEach(function (section) {
      var list = section.querySelector('ol.tasks');
      section.classList.toggle('search-hidden', !!query && !groupHasVisibleTask(list));
    });

    document.querySelectorAll('.completed-group').forEach(function (group) {
      var list = group.querySelector('ol.tasks');
      group.classList.toggle('search-hidden', !!query && !groupHasVisibleTask(list));
    });
  }

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
      var update = {
        id: taskId,
        notes: textarea ? textarea.value : '',
        status: li.dataset.status || 'open',
        priority: li.dataset.priority || 'medium',
        due_date: dueInput ? dueInput.value : '',
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

  fetch('/tasks.json')
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Could not load tasks.json (status ' + response.status + ')');
      }
      return response.json();
    })
    .then(render)
    .catch(function (err) {
      sectionsContainer.textContent = 'Failed to load tasks: ' + err.message +
        '. If you opened this file directly, run a local server instead (see README.md).';
    });
})();