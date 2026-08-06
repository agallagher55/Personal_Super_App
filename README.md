# Personal Tasks Tracker

Files:

- `html/index.html`, the page shell for the main task list (also reused for
  single-category views, see below)
- `html/new-task.html`, the "add a task" form page, served at `/tasks/new`
- `html/tasks-index.html` / `static/js/tasks-index.js`, the category table of
  contents page, served at `/tasks`
- `static/styles/styles.css`, all styling
- `static/js/script.js`, plain JavaScript for the main page, no modules, no build step
- `static/js/new-task.js`, plain JavaScript that fills the form's section dropdown
- `backend/server.py`, a small custom server (see below, this is what makes
  saving new tasks actually work); `backend/start-server.bat` runs it for
  double-click use on Windows
- `data/tasks.json`, the task data (sections, descriptions, notes, tags, done status)

## Running it

Browsers block `fetch()` of local files opened via `file://` for
security reasons, so double-clicking `html/index.html` won't load the tasks.
This also has to be Python's server rather than a generic static
server, since the new-task form needs somewhere to POST to.

```bash
python3 backend/server.py
```

Then open http://localhost:8000 in your browser. `backend/start-server.bat`
runs this same command for double-click use.

## Browsing by category

Go to `http://localhost:8000/tasks` for a table of contents listing
every section (Work Tasks, Finance, Admin, Research, Covering for Mike
Potter) with its task count, each linking to a page showing just that
one category. Each section has a short slug used in its URL:

- `/tasks/work`
- `/tasks/finance`
- `/tasks/admin`
- `/tasks/research`
- `/tasks/mike`

These category pages are the same app as the main page (status
dropdowns, notes, Save Changes, delete all work identically), just filtered to
one section, with a "&larr; All categories" link back to `/tasks`. The
**+ New Task** button on a category page pre-selects that category in
the form. Slugs live in each section's `"slug"` field in `data/tasks.json`,
add one there if you add a new section by hand.

## Adding a task from the browser

Click **+ New task** in the header, or go straight to
`http://localhost:8000/tasks/new`. Fill in the section, description,
and optionally a note, a priority tag, other tags (comma separated),
and whether it's already done. Submitting POSTs to `/tasks/new`, which
`backend/server.py` handles by appending the task to the matching section in
`data/tasks.json` and writing the file back to disk, then redirects you back
to the main page with a "Task added" confirmation.

## Editing tasks

Open `data/tasks.json` and edit directly, no HTML knowledge needed:

- `id`, a unique identifier auto-assigned to every task, this is what
  the Save Changes button uses to match a task in the browser back to
  its entry in the file, don't reuse an id across tasks
- `desc`, the task text
- `note`, the fixed descriptive detail shown under the task (leave as
  `""` for none)
- `notes`, your own freeform scratch notes typed into the Notes box on
  each task, saved to disk via the Save Changes button
- `tags`, an array of `{ "text": "...", "flag": true|false }`, `flag: true`
  renders the tag in red (used for the most urgent/important tags)
- `done`, `true` or `false`, kept in sync with `status` (`true` only
  when `status` is `"done"`), done tasks are pulled out into the
  Completed panel automatically
- `status`, one of `"open"`, `"in-progress"`, or `"done"`, set via the
  status dropdown on each task
- `created`, the UTC timestamp the task was added, set automatically
  and never changed afterward
- `modified`, the UTC timestamp of the task's last notes or status
  change, updated automatically
- `completed`, the UTC timestamp `status` last became `"done"`, or
  `""` if the task isn't done
- a section can also have its own top-level `"note"` field, shown under
  its header (used for reference info that isn't tied to one task, like
  the TD rate note under Finance)

To add a new task by hand instead of using the form, copy an existing
task object within a section's `tasks` array and give it a unique
`id`. To add a new section, copy a whole section object at the top
level and give it a unique `id`.

## Behavior

- Each task has a status dropdown (Open / In Progress / Done). Setting
  a task to Done moves it out of its section and into the
  **Completed** panel on the right, grouped under its original section
  label. Setting it back to Open or In Progress there moves it back to
  its section.
- The Completed panel is collapsed by default, click its header to
  expand it. Each category group inside it is independently
  collapsible too, click a group's label to toggle just that group.
- Click any section header to collapse or expand it.
- Drag a section by its header to reorder it relative to the other
  sections, this works whether the section is expanded or collapsed.
- Typing in a task's Notes box and clicking the floating **Save
  Changes** button (bottom right) POSTs every task's current notes
  text and checked state to `/tasks/update`, which `backend/server.py` writes
  back into `data/tasks.json` on disk, matched by each task's `id`. A small
  "Saved" confirmation appears near the button.
- Each task has a small &times; button that permanently deletes it.
  Clicking it asks for confirmation first, then POSTs to
  `/tasks/delete`, which removes that task from `data/tasks.json` on disk
  immediately, this is not undoable and does not require pressing Save
  Changes first.
- Collapsed sections and section drag order still reset on page
  refresh, those aren't persisted. Notes and done state persist once
  you click Save Changes; tasks added through the `/tasks/new` form
  are saved immediately on submit.