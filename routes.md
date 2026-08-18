# Routes

How URLs map to HTML pages, their JS, and the backend handlers in
`backend/server.py`. Data lives in three normalized files —
`data/sections.json`, `data/tasks.json`, `data/tags.json` — joined on the
fly into the nested shape below and served read-only at `/tasks.json`,
mutated only through the POST routes below.

## GET routes

| Route | Serves | Frontend JS | Notes |
|---|---|---|---|
| `/` | `html/index.html` | `static/js/script.js` | All sections, unfiltered. |
| `/tasks` | `html/tasks-index.html` | `static/js/tasks-index.js` | Category (section) list with open/closed counts. |
| `/tasks/new` | `html/new-task.html` | `static/js/new-task.js` | New task form. `?section=<id>` preselects a section. |
| `/tasks/new-category` | `html/new-category.html` | — | New category (section) form. |
| `/tasks/<slug>` | `html/index.html` | `static/js/script.js` | Same page as `/`, but `script.js` reads the slug from the URL and renders only the matching section. 404 if `<slug>` doesn't match any section's `slug`. |
| `/task/<id>` | `html/task-detail.html` | `static/js/task-detail.js` | Edit/delete a single task by id. 404 if `<id>` doesn't exist. |
| `/fitness` | `html/fitness.html` | — | Placeholder page for personal fitness tracking. |
| `/finance` | `html/finance.html` | — | Placeholder page for personal finance tracking. |
| `/new` | — | — | 302 redirect to `/tasks/new`. |
| `/tasks.json` | `sections.json` + `tasks.json` + `tags.json`, joined | — | `no-store` cache headers. Every page above fetches this client-side to render. |

Any other path falls through to `SimpleHTTPRequestHandler`, i.e. plain
static file serving from the repo root (`/static/...`, etc.).

## POST routes

| Route | Handler | Effect |
|---|---|---|
| `/tasks/new` | `handle_new_task` | Appends a row to `tasks.json` (`section_id` foreign key) and any tags to `tags.json`. Redirects `303` to `/?added=1`. |
| `/tasks/new-category` | `handle_new_category` | Appends a new (empty) row to `sections.json`, slugified from `label`. Redirects `303` to `/tasks?added=1`. 400 if the name is empty or a category with that slug/id already exists. |
| `/tasks/update` | `handle_update_tasks` | Bulk update by task id (desc, note, tags, notes, status, priority, ticket_number, assignment_group, requested_by, due_date, reorder). Writes `tasks.json` and, if tags changed, `tags.json`. Returns JSON. |
| `/tasks/delete` | `handle_delete_task` | Removes a task from `tasks.json` and its tags from `tags.json`. Returns JSON. |

## Sections (current `data/sections.json`)

Each section has an `id` (used by the `section` field on `/tasks/new`, the
`section_id` foreign key on tasks, and in `tasks/update` payloads) and a
`slug` (used in the `/tasks/<slug>` URL).

| id | slug | label |
|---|---|---|
| `own-tasks` | `work` | Work Tasks |
| `finance-tasks` | `finance` | Finance |
| `admin-tasks` | `admin` | Admin |
| `research-tasks` | `research` | Research |
| `mike-coverage` | `mike` | Covering for Mike Potter |

New sections can be added via the `/tasks/new-category` form (from the
"+ New Category" link on `/tasks`), which slugifies the given name into
both `id` and `slug`. They can still be added by hand by editing
`data/sections.json` directly, as long as `id`/`slug` stay unique, since
`/tasks/<slug>` and the `section-select` dropdown on `/tasks/new` both
read sections from there directly.
