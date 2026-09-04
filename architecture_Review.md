# Architecture Review — Personal Super App

Reviewed 2026-08-17. Scope: everything in the repo at the time of review —
`backend/server.py`, `html/`, `static/`, `data/tasks.json`, `service_now/`,
`render.yaml`, and the docs (`README.md`, `DEPLOYMENT.md`, `routes.md`).

**Since diverged (as of 2026-09-04):** `/fitness` and `/finance` are no
longer the two placeholder stubs §1 describes below. `/fitness` is now a
fully working per-visitor Google Health dashboard with real OAuth
sign-in — see `fitness/README.md` and `fitness/ARCHITECTURE.md`.
`/finance` grew a real, working dashboard UI (still reading a static
seed file; the Plaid sync layer is fully planned but not yet built) —
see `finance/README.md` and `finance/ARCHITECTURE.md`. §8 item 6
("decide the fate of `/fitness` and `/finance`") is resolved by the
same two docs. `roadmap.html` tracks current status; everything else
below (the tasks-tracker/backend findings and recommended priorities
1–5) is unaffected and still applies.

## 1. What this app actually is today

Despite the "Super App" name, this is a **single-page personal task
tracker** with two placeholder stubs (`/fitness`, `/finance`) that render
static "coming soon" text and have no backend behind them. There's one
real feature end to end: task/category CRUD backed by a flat JSON file,
plus a standalone, unwired ServiceNow import script.

**Stack:**
- Backend: Python 3 stdlib only — `http.server.SimpleHTTPRequestHandler` +
  `socketserver.TCPServer`, no framework, no dependencies.
- Frontend: hand-written vanilla JS (no build step, no bundler, no
  framework), plain CSS, static HTML pages per route.
- Data store: a single JSON file (`data/tasks.json`) read/written wholesale
  on every request.
- Deployment: Render, via `render.yaml`, with a persistent disk mounted
  over `data/` so the JSON file survives redeploys.
- Integration: a separate, manually-run ServiceNow sync script
  (`service_now/sync.py`) that also reads/writes `data/tasks.json`
  directly, with no interaction with the running server.

This is a reasonable shape for a single-user personal tool prototyped
quickly, and the docs are honest about that scope. The findings below are
mainly about what breaks first as usage grows, not "wrong" choices for
what it is today.

## 2. Backend (`backend/server.py`)

**Structure:** one file, one handler class, route dispatch via a long
if/elif chain on `parsed.path` in `do_GET`/`do_POST`. No routing
abstraction, no middleware, no separation between "route table" and
"business logic" — request parsing, validation, data mutation, and
response writing are all inline in each `handle_*` method.

### Findings

- **No concurrency safety on the datastore.** Every handler does
  read-whole-file → mutate in memory → write-whole-file, with no locking.
  `socketserver.TCPServer` (not `ThreadingTCPServer`) serves one request
  at a time by default, which *happens* to avoid races today, but it's an
  accident of the current server class, not a designed guarantee — any
  future move to threads/async, or two browser tabs racing a save, can
  silently drop one writer's changes (last write wins, whole file). There's
  also no atomic write (no write-to-temp-then-rename), so a crash or
  power loss mid-`json.dump` can truncate `tasks.json` and lose all data.
- **No backups/versioning of `tasks.json`.** It's the sole datastore, and
  `handle_delete_task` is instant and irreversible (`del tasks[i]` then
  write) with only a client-side `confirm()` standing between a click and
  permanent data loss. A single corrupted write or an accidental section
  overwrite has no recovery path other than the last git commit.
- **No auth of any kind.** Every mutating endpoint (`/tasks/new`,
  `/tasks/update`, `/tasks/delete`, `/tasks/new-category`) is open to
  anyone who can reach the port. Fine for `localhost`; once deployed to
  Render with a public URL (per `DEPLOYMENT.md`), the task list — plus
  whatever's in it (ServiceNow ticket numbers, names of coworkers, notes)
  — is world-readable and world-writable/deletable by URL guessing alone.
  There's no `.htaccess`-equivalent, no session, no API key, nothing.
- **Whole-file read/write scales linearly and won't survive growth.**
  Every GET of `/tasks.json` and every mutation reads and
  re-serializes the entire file. Fine at hundreds of tasks; becomes the
  dominant cost as sections/tasks grow, and there's no pagination story
  since the frontend always fetches everything.
- **Manual request parsing duplicates a lot of framework work.** Hand
  rolled `parse_qs` on `do_POST`, hand-rolled JSON validation per field,
  hand-rolled 400/404/303 responses, hand-rolled CORS-less same-origin
  assumptions. Stdlib-only is a deliberate simplicity choice per the docs
  and `service_now/README.md` ("matches the rest of this repo"), but it
  means every new field or endpoint repeats the same boilerplate
  (`fields.get('x', [''])[0].strip()`, manual `changed` tracking) rather
  than being schema-declared once.
- **No input validation beyond a few required-field checks.** `desc` and
  `section` are required for new tasks, but there's no length limits, no
  HTML-escaping guarantees enforced server-side (frontend happens to use
  `textContent` in most places, but that's a frontend convention, not a
  backend contract), and `due_date`/other free-text fields accept
  anything.
- **`section_slug_exists`/`find_task` re-read and re-parse the whole file
  on every single request**, including ones that already load it again a
  few lines later in the same code path (e.g. a `GET /task/<id>` reads
  the file once to check existence, then the page's own client-side JS
  fetches `/tasks.json` and re-parses again to actually render). Not a
  performance problem yet, but it's duplicated I/O with no caching layer.
- **No logging.** Failed writes, malformed payloads, and 400s are only
  visible if a client happens to display them; there's no server-side
  audit trail of who changed/deleted what and when (relevant given there's
  no auth to attribute changes to a user in the first place).
- **No tests.** There is no test suite anywhere in the repo (confirmed via
  search) for either the backend handlers or the sync script. Every route
  behavior (redirects, 400s on missing fields, upsert-by-id matching
  logic) is unverified by anything except manual clicking.
- **`format_sentence`'s sentence-splitting regex** is a content-formatting
  opinion baked into the server (auto-capitalizing/punctuating `desc` and
  `note`), which is an unusual place for presentation logic to live and
  will mis-format anything containing abbreviations, URLs, or
  intentional lowercase.

## 3. Frontend (`html/`, `static/js/`, `static/styles/`)

**Structure:** one HTML shell per route, each pulling in its own
matching JS file (`script.js`, `new-task.js`, `tasks-index.js`,
`task-detail.js`), all IIFEs with no shared modules, no imports, and no
build step. All four JS files independently `fetch('/tasks.json')` and
re-implement their own subset of "find a task/section," rather than
sharing a data-access layer.

### Findings

- **Every page re-fetches and re-parses the entire `tasks.json` file**,
  even `task-detail.html` which only needs one task, and
  `tasks-index.html` which only needs section-level counts. There's no
  per-resource endpoint (`GET /task/<id>` returns HTML, not JSON), so the
  "API" is really just "the whole file," and every screen pays for the
  full dataset.
- **Duplicated logic across files with no shared module.** Tag-building,
  `findTask`-style scanning, date formatting (`formatDate` is
  reimplemented slightly differently in `script.js` vs
  `task-detail.js`), and the fetch-and-render boilerplate are copy-pasted
  per page rather than factored into a shared `static/js/api.js` or
  similar. A schema change (e.g. renaming a field) means hunting through
  four files.
- **No client-side framework/state management**, which is a fine choice
  at this scale, but `script.js` at 750+ lines is already doing manual
  DOM diffing-by-hand (moving `<li>` elements between completed/active
  lists, manually renumbering, manually toggling classes) — the kind of
  bookkeeping a component model would otherwise guarantee. This is the
  file most likely to accumulate quiet bugs as more interactions are
  added (e.g. drag-reorder + status-change + search-filter all mutate
  overlapping DOM state today).
- **No optimistic-update rollback consistency.** `deleteTask` adds a
  `.deleting` class then removes the element only after the network call
  succeeds (good), but the Save Changes flow (`/tasks/update`) has no
  equivalent per-field rollback — if the request fails, the UI still
  shows the edited (unsaved) state with just an error toast, so a user
  can believe something saved when it didn't.
- **Two `innerHTML` assignments driven by data fields**
  (`footnoteEl.innerHTML = data.footnote` in `script.js`, and the
  meta-info block in `task-detail.js`, which is built from static labels
  but concatenated with `formatDate` output). `footnote` currently comes
  from a trusted, manually-edited JSON file, but the moment any UI is
  added to edit it (the way notes/tags already are editable from the
  browser), this becomes a stored-XSS path — worth switching to
  `textContent`/DOM construction now rather than after such a field
  becomes user-editable.
- **No client-side validation mirrored from the backend.** E.g.
  `new-task.html`'s form relies entirely on the server's 400 responses
  for required-field enforcement beyond basic HTML5 `required`.
- **No accessibility pass evident**: drag-and-drop reordering (sections
  and tasks) has no keyboard-equivalent, so reordering is mouse-only.
- **No responsive/mobile layout indicated** in a quick pass of
  `styles.css` — worth confirming on a phone-width viewport if this is
  meant to be used outside a desktop browser.

## 4. Data model (`data/tasks.json`)

- **Single JSON file as the datastore** is the load-bearing architectural
  decision for the whole app and is explicitly called out in the docs as
  the reason GitHub Pages doesn't work. It's appropriate for a personal,
  single-user tool but is the first thing to outgrow if this becomes
  multi-user or grows past a few hundred tasks — no querying, no indices,
  no concurrent-writer story (see backend section).
- **Schema drift risk**: task objects carry both `done` (bool) and
  `status` (`open`/`in-progress`/`done`) as parallel redundant fields
  that must be kept in sync by every write path (`handle_new_task`,
  `handle_update_tasks`, `service_now/sync.py` all independently set
  both). Three separate places implementing "done ⇔ status==done" is a
  bug waiting to happen if a fourth write path is added and misses it.
- **`servicenow_sys_id` is only added by the sync script**, not part of
  the schema the main server/frontend know about — it's silently carried
  through `handle_update_tasks` only because that handler does
  field-by-field allow-listing that happens not to touch it, which is
  fragile coupling between two independently-evolving write paths.

## 5. ServiceNow integration (`service_now/`)

- **Well-isolated and honest about its limitations** (the README calls
  out an unconfirmed `sys_class_name` mapping and documents it clearly —
  good practice).
- **Completely disconnected from the running app.** It's a manual CLI
  script that mutates the same `tasks.json` file out from under the
  server process, with no coordination — if `sync.py` runs while
  `backend/server.py` has just read the file and is about to write back
  a user's in-browser edit, the sync's changes can be silently clobbered
  (last write wins, whole-file overwrite, same root cause as the backend
  concurrency finding above). There's no lock file, no "server is
  running" check, nothing.
- Credentials handling is reasonable for a personal script (`.env`
  git-ignored, stdlib-only dotenv loader, Basic/OAuth both supported), but
  Basic auth password is kept in plaintext on disk with no secrets
  manager — acceptable for local-only personal use, not for anything
  shared.

## 6. Deployment (`render.yaml`, `DEPLOYMENT.md`)

- Correctly identifies that GitHub Pages can't host this (needs a
  writable backend) and picks Render with a persistent disk — sound
  reasoning, clearly documented.
- **Free-tier spin-down** is called out and accepted as a tradeoff — fine
  for personal use.
- **No environment separation** (no staging vs. production), no CI, no
  automated deploy checks — a bad push goes straight to the one live
  instance whose disk holds the only copy of the data.
- **No backup strategy for the Render persistent disk.** If the disk is
  ever lost/corrupted, the only fallback is whatever's committed to git
  (a stale seed snapshot), not the live data.

## 7. Cross-cutting

- **No CI/CD pipeline** (no `.github/workflows`, no lint/test step found
  anywhere in the repo) — nothing runs automatically on push besides
  Render's own auto-deploy.
- **No dependency management file** (no `requirements.txt`/`pyproject.toml`)
  — intentional, since everything is stdlib-only; worth keeping an eye on
  if any future feature (e.g. real auth, a real DB) needs a third-party
  package, since there's currently no place to declare one.
- **Docs are unusually good** for a project this size — `README.md`,
  `DEPLOYMENT.md`, `routes.md`, and `service_now/README.md` are all
  accurate, current, and describe real behavior rather than aspirational
  behavior. This significantly reduces onboarding risk despite the lack
  of tests.

## 8. Recommended priorities

Roughly in order of "cheapest fix for the risk it removes":

1. **Atomic writes** for `tasks.json` (write to a temp file in the same
   directory, then `os.replace` over the original) — a few lines, removes
   the truncation-on-crash risk entirely.
2. **A file lock** (e.g. `fcntl.flock` on POSIX, or a simple lock file)
   around read-modify-write in both `backend/server.py` and
   `service_now/sync.py` — closes the cross-process race between the
   server and the sync script, and future-proofs against ever switching
   to a threading server.
3. **Minimal auth** (even a single shared-secret header/cookie checked
   before any mutating route) before this is relied on while deployed
   publicly on Render — right now anyone with the URL can delete every
   task.
4. **A basic test suite** for `backend/server.py`'s handlers (spin up the
   server against a temp `tasks.json`, hit routes with `urllib`/`requests`,
   assert status codes and resulting file contents) — this is the
   highest-leverage gap given how much hand-rolled parsing/mutation logic
   exists with zero verification today.
5. **Extract a tiny shared frontend module** (`static/js/api.js`) for
   `fetch('/tasks.json')` + task/section lookup + date formatting, used by
   all four page scripts, to stop the four-way duplication before a fifth
   page is added.
6. **Decide the fate of `/fitness` and `/finance`.** They're pure
   placeholders today; either scope real functionality (which will need
   their own data model decisions informed by the same concurrency/schema
   points above) or drop them from the nav until there's something behind
   them, since dead nav links are confusing in what's otherwise a tight,
   working app.

## 9. What's genuinely solid

Worth naming, since a review like this skews toward findings: the routing
table is simple and legible, `routes.md` and the schema docs in
`README.md` are accurate and well-maintained, the ServiceNow sync's
upsert-by-`sys_id`-then-`ticket_number` matching is a sensible way to
avoid duplicate imports, and the choice to stay stdlib-only/no-build-step
is consistent and clearly intentional rather than accidental — it keeps
the whole system inspectable in one sitting, which is a real property or
this whole review would have taken far longer.
