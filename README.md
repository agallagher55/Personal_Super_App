# Personal Tasks Tracker

Files:

- `html/tasks/index.html`, the page shell for the main task list (also reused for
  single-category views, see below)
- `html/tasks/new-task.html`, the "add a task" form page, served at `/tasks/new`
- `html/tasks/tasks-index.html` / `static/js/tasks-index.js`, the category table of
  contents page, served at `/tasks/categories`
- `static/styles/styles.css`, all styling
- `static/js/script.js`, plain JavaScript for the main page, no modules, no build step
- `static/js/new-task.js`, plain JavaScript that fills the form's section dropdown
- `backend/server.py`, a small custom server (see below, this is what makes
  saving new tasks actually work); `backend/start-server.bat` runs it for
  double-click use on Windows
- `data/tasks.db`, the task data, in three normalized SQLite tables
  (`sections`, `tasks`, `tags`, one row each, joined by id). Created by
  `backend/tasks_db.py`; see `DATABASE-MIGRATION.md` for the schema
- `data/sections.json`, `data/tasks.json`, `data/tags.json`, the seed data
  the database was imported from. Kept as a readable, git-committed
  fallback, but **no longer live**: the running app does not read or write
  them any more
- `backend/tasks_db.py`, `backend/tasks_schema.sql`, the storage layer and
  its DDL

## Running it

Browsers block `fetch()` of local files opened via `file://` for
security reasons, so double-clicking `html/tasks/index.html` won't load the tasks.
This also has to be Python's server rather than a generic static
server, since the new-task form needs somewhere to POST to.

```bash
python3 backend/server.py
```

Then open http://localhost:8000/tasks in your browser (the task tracker
lives under `/tasks`; `/` itself is the app's dashboard home page, see
`routes.md`). `backend/start-server.bat` runs this same command for
double-click use.

## Deploying

See [DEPLOYMENT.md](DEPLOYMENT.md) — GitHub Pages won't work for this
app (it needs `backend/server.py` running, not just static files), so
it deploys to Render instead.

## Browsing by category

Go to `http://localhost:8000/tasks/categories` for a table of contents listing
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
one section, with a "&larr; All categories" link back to `/tasks/categories`. The
**+ New Task** button on a category page pre-selects that category in
the form. Slugs live in each section's `slug` column, set automatically from the
category name when you add one through **+ New category**.

## Adding a task from the browser

Click **+ New task** in the header, or go straight to
`http://localhost:8000/tasks/new`. Fill in the section, description,
and optionally a note, a priority tag, other tags (comma separated),
and whether it's already done. Submitting POSTs to `/tasks/new`, which
`backend/server.py` handles by inserting a row into `tasks` (and any tags
into `tags`, in the same transaction), then redirects you back to the main
page with a "Task added" confirmation.

## Editing tasks

The data lives in `data/tasks.db`, a SQLite database. Day to day you edit
it through the app: the status dropdowns, the Notes boxes, drag-and-drop
reordering, **+ New task**, and **+ New category** all write to it.

For a one-off change the UI can't make, use the `sqlite3` CLI (bundled with
Python, so `python3 -c "import sqlite3"` proves you have it) or a GUI like
[DB Browser for SQLite](https://sqlitebrowser.org/):

```bash
sqlite3 data/tasks.db "SELECT id, status, \"desc\" FROM tasks LIMIT 5;"
sqlite3 data/tasks.db "UPDATE tasks SET priority = 'high' WHERE id = '...';"
```

This is the one thing the move off flat JSON took away: you can no longer
open the store in a text editor. In exchange, a half-written save can no
longer truncate it, a task and its tags can no longer disagree after a
crash, and a typo can no longer produce invalid JSON that silently reads
back as an empty task list.

Stop the server before writing to the database by hand, so your change and
a concurrent save don't race.

The columns, which are also what the three seed JSON files hold:

- `sections`:
  - `id`, a unique identifier for the section, referenced by tasks as
    `section_id`
  - `label`, the display name shown in the header
  - `slug`, used in category URLs like `/tasks/finance`
  - `position`, where the section sorts on the page (lower first)
  - `note`, an optional top-level note shown under the section header
    (used for reference info that isn't tied to one task, like the TD
    rate note under Finance), `""` for none
- `tasks`:
  - `id`, a unique identifier auto-assigned to every task, this is what
    the Save Changes button uses to match a task in the browser back to
    its entry in the file, don't reuse an id across tasks
  - `section_id`, which section this task belongs to, matches a
    section's `id`
  - `position`, where the task sorts within its section (lower first)
  - `desc`, the task text
  - `note`, the fixed descriptive detail shown under the task (leave as
    `""` for none)
  - `notes`, your own freeform scratch notes typed into the Notes box on
    each task, saved to disk via the Save Changes button
  - `done`, `true` or `false`. A **generated column**, computed from
    `status` on every read rather than stored, so the two can never
    disagree. It's read-only: change `status` instead. Done tasks are
    pulled out into the Completed panel automatically
  - `status`, one of `"open"`, `"in-progress"`, `"pending"`, `"done"`, or
    `"cancelled"`, set via the status dropdown on each task
  - `created`, the UTC timestamp the task was added, set automatically
    and never changed afterward
  - `modified`, the UTC timestamp of the task's last notes or status
    change, updated automatically
  - `completed`, the UTC timestamp `status` last became `"done"`, or
    `""` if the task isn't done
- `tags`:
  - `id`, a unique identifier for the tag
  - `task_id`, which task this tag belongs to, matches a task's `id`.
    Deleting a task deletes its tags with it
  - `position`, where the tag sorts within its task
  - `text`, the tag's label
  - `flag`, `true` or `false`, `true` renders the tag in red (used for
    the most urgent/important tags)

`GET /tasks.json` (what the frontend actually fetches) joins these three
tables back into the nested `{ sections: [{ tasks: [{ tags: [...] }] }] }`
shape on every request, so the browser-facing API is byte-for-byte what it
was when the store was three JSON files.

`tasks` has more columns than are listed above (`ticket_number`,
`assignment_group`, `requested_by`, `due_date`, `time_estimate`,
`related_files`, `parent_id`, `work_type`, `env_dev`/`env_qa`/`env_prod`,
`cmdb_updated`, `servicenow_sys_id`) driving the task detail view and the
ServiceNow sync. `backend/tasks_schema.sql` is the full, commented list.

### Setting up the database

A fresh clone has no `data/tasks.db`; the server creates an empty one on
startup. To load the committed seed data into it instead, run this once:

```bash
python3 backend/tasks_db.py migrate
```

It imports `data/sections.json`, `data/tasks.json`, and `data/tags.json`,
prints a row count per table, leaves the JSON files untouched, and refuses
to run twice against a database that already has rows.

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
  back into `data/tasks.json` (and `data/tags.json` if tags changed) on disk,
  matched by each task's `id`. A small "Saved" confirmation appears near the
  button.
- Each task has a small &times; button that permanently deletes it.
  Clicking it asks for confirmation first, then POSTs to
  `/tasks/delete`, which removes that task from `data/tasks.json` (and its
  tags from `data/tags.json`) on disk immediately, this is not undoable and
  does not require pressing Save Changes first.
- Collapsed sections and section drag order still reset on page
  refresh, those aren't persisted. Notes and done state persist once
  you click Save Changes; tasks added through the `/tasks/new` form
  are saved immediately on submit.