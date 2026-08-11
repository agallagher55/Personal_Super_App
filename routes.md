# Routes

How URLs map to HTML pages, their JS, and the backend handlers in
`backend/server.py`. Data lives in `data/tasks.json`, served read-only at
`/tasks.json` and mutated only through the POST routes below.

## GET routes

| Route | Serves | Frontend JS | Notes |
|---|---|---|---|
| `/` | `html/index.html` | `static/js/script.js` | All sections, unfiltered. |
| `/tasks` | `html/tasks-index.html` | `static/js/tasks-index.js` | Category (section) list with open/closed counts. |
| `/tasks/new` | `html/new-task.html` | `static/js/new-task.js` | New task form. `?section=<id>` preselects a section. |
| `/tasks/<slug>` | `html/index.html` | `static/js/script.js` | Same page as `/`, but `script.js` reads the slug from the URL and renders only the matching section. 404 if `<slug>` doesn't match any section's `slug`. |
| `/task/<id>` | `html/task-detail.html` | `static/js/task-detail.js` | Edit/delete a single task by id. 404 if `<id>` doesn't exist. |
| `/new` | — | — | 302 redirect to `/tasks/new`. |
| `/tasks.json` | `data/tasks.json` | — | Raw data, `no-store` cache headers. Every page above fetches this client-side to render. |

Any other path falls through to `SimpleHTTPRequestHandler`, i.e. plain
static file serving from the repo root (`/static/...`, etc.).

## POST routes

| Route | Handler | Effect |
|---|---|---|
| `/tasks/new` | `handle_new_task` | Appends a task to the given section in `tasks.json`. Redirects `303` to `/?added=1`. |
| `/tasks/update` | `handle_update_tasks` | Bulk update by task id (desc, note, tags, notes, status, priority, ticket_number, assignment_group, requested_by, due_date, reorder). Returns JSON. |
| `/tasks/delete` | `handle_delete_task` | Removes a task by id. Returns JSON. |

## Sections (current `data/tasks.json`)

Each section has an `id` (used by the `section` field on `/tasks/new` and
in `tasks/update` payloads) and a `slug` (used in the `/tasks/<slug>` URL).

| id | slug | label |
|---|---|---|
| `own-tasks` | `work` | Work Tasks |
| `finance-tasks` | `finance` | Finance |
| `admin-tasks` | `admin` | Admin |
| `research-tasks` | `research` | Research |
| `mike-coverage` | `mike` | Covering for Mike Potter |

Adding a new section means adding an entry to `data/tasks.json`'s
`sections` array with a unique `id` and `slug` — no server changes needed,
since `/tasks/<slug>` and the `section-select` dropdown on `/tasks/new`
both read sections from `tasks.json` directly.
