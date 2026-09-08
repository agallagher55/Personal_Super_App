# Architecture Review — Personal Super App

Reviewed against the repository on **2026-09-08**. This is a current-state
review, not an implementation plan. Detailed feature contracts live in
`routes.md`, `fitness/`, `finance/`, and `DATABASE-MIGRATION.md`.

## 1. Current system

The project is one Python stdlib web service with four user-facing areas:

- `/`: a summary dashboard;
- `/tasks`: a SQLite-backed task and category manager, including a scratchpad
  and a standalone ServiceNow importer;
- `/fitness`: a per-visitor Google OAuth/Google Health dashboard; and
- `/finance`: CSV/PDF transaction ingestion, spending and cash-flow views,
  manual balance history, and a partly static net-worth dashboard.

`backend/server.py` uses `http.server.ThreadingHTTPServer` and a single
`SimpleHTTPRequestHandler` subclass. Route dispatch and request handling are
explicit `if` branches. The browser code is vanilla JavaScript and CSS with no
build step. Application code is stdlib-only except for the optional Shakepay
PDF importer, which needs `pypdf`.

Persistent state is split by domain:

| Domain | Live store | Notes |
|---|---|---|
| Tasks | `data/tasks.db` | Normalized SQLite tables; committed JSON files are exportable snapshots only. |
| Finance | `data/finance/finance.db` | SQLite transactions and balance snapshots; import audit copies also live under `data/finance/`. |
| Fitness | `data/fitness/users/<user_id>/` | Per-user tokens, profile, and cached health data as JSON; the session secret and optional allowlist also live under `data/fitness/`. |

Render mounts one persistent disk over `data/`. Both `data/finance/` and
`data/fitness/` are intentionally git-ignored because they contain private
financial, health, and credential data.

## 2. What is solid

- **Small operational surface.** One process, no frontend toolchain, and very
  few dependencies make local startup and debugging straightforward.
- **Task writes are materially safer than the original flat-file design.**
  SQLite transactions, foreign keys, generated `done` state, and deterministic
  JSON export remove partial multi-file writes and status drift.
- **Fitness identity isolation is deliberate.** Signed session/state cookies,
  a fail-closed allowlist, per-user token/data directories, same-origin checks
  on its POST routes, and routine reauthorization handling are documented and
  tested.
- **Finance ingestion preserves useful provenance.** Imports are repeatable,
  source-aware, and retain audit copies; category corrections and cash-flow
  exclusions are modeled separately from imported facts.
- **The design system and route contract are centralized.** `DESIGN-SYSTEM.md`
  describes shared UI primitives, while `routes.md` maps the actual HTTP
  surface.

## 3. Current risks and limitations

### Access control and privacy

Fitness has its own sign-in gate, but `/tasks`, `/finance`, their JSON reads,
and their mutation/import routes do not. A public Render URL therefore exposes
private tasks and financial data and allows unauthenticated changes. Same-origin
checks on finance mutations reduce cross-site request forgery but do not
authenticate a visitor. A whole-app authentication layer is the highest-priority
security gap before sharing or treating the deployment as private.

### Backups and deployment

The persistent disk is the live source for all three domains, but the repository
contains no automated backup/restore workflow. Task JSON exports are manual and
do not cover finance or fitness. There is also no staging environment, health
check endpoint configured in `render.yaml`, or CI workflow, so tests are not
run automatically before Render deploys a pushed commit.

### Server organization

`backend/server.py` combines routing, validation, HTTP response construction,
and orchestration in one large handler. This remains readable at the current
scale but increases regression risk as routes accumulate. Shared JSON/form
validation and domain-specific route modules would give the most benefit
without requiring a framework migration.

`ThreadingHTTPServer` prevents a slow quote request from blocking all clients.
SQLite serializes database writes, and the fitness sync has a per-user lock, but
there are no load or concurrency tests documenting behavior under contention.

### Frontend maintainability and accessibility

The no-build vanilla approach remains appropriate, but state and rendering
logic are spread across page-specific scripts. Task pages independently fetch
the complete nested `/tasks.json` payload, even when a page needs only one task
or category counts. There is no pagination or resource-specific task JSON API.
This is acceptable for a personal dataset but scales with the entire task list.

Drag-and-drop task/category ordering has no documented keyboard equivalent.
The project has responsive breakpoints and viewport metadata, but no automated
accessibility checks or browser-level tests.

### Feature completeness

- Finance's Spending and Cash Flow sections are live, and manual balance
  snapshots exist, but the primary net-worth cards/charts still render the
  sample `static/finance/finance-dashboard.json`; investment holdings and the
  raw/staging finance layer remain planned in `finance/ARCHITECTURE.md`.
- ServiceNow sync is manual only. Its Chat Queue Entry table name remains
  unverified for the target ServiceNow instance.
- Google Health temperature reshaping remains unverified against a real synced
  temperature data point.
- Render plan availability, pricing, disk support, and current Google
  OAuth/Health policy details are external facts and should be rechecked in
  their official consoles/docs before a new production deployment.

## 4. Testing posture

There are unit tests for the task database/export layer, finance database and
summary/import logic, and fitness sessions/users/token claims. There are no
end-to-end HTTP tests, frontend tests, ServiceNow tests, finance quote-proxy
tests, lint/type-check configuration, or CI workflow. The suite uses
`unittest`; the repository does not define a single canonical test command.
Run each test directory explicitly because `unittest` discovery does not
recurse into these directories unless they are Python packages:

```bash
for dir in backend/tests backend/finance/tests backend/fitness/tests; do
  python3 -m unittest discover -s "$dir" -p 'test_*.py'
done
```

The Shakepay importer is the only documented optional dependency and its tests
may require `pypdf` to be installed.

## 5. Recommended priorities

1. Put `/tasks` and `/finance` (pages, reads, and writes) behind authentication;
   decide explicitly whether fitness's Google identity can serve as the common
   identity or whether the whole app needs a separate gate.
2. Automate encrypted backups and perform a documented restore drill for
   `data/tasks.db`, `data/finance/`, and `data/fitness/`.
3. Add CI that runs the full unit suite and a small HTTP smoke suite before
   deployment.
4. Split `backend/server.py` by domain while retaining the current stdlib server
   if the low-dependency constraint remains valuable.
5. Add keyboard-accessible reordering and automated accessibility/browser
   checks.
6. Complete the finance dashboard's switch from sample net-worth JSON to its
   real snapshot tables before presenting those figures as live.

## 6. Knowledge gaps from this review

The repository cannot establish several environment-specific facts. They need
owner access or live external verification:

- whether `chat_queue_entry` is the correct `sys_class_name` in the Halifax
  ServiceNow instance;
- whether real temperature records match the current Google Health reshaper;
- which Render plan is actually attached to the deployed service, whether its
  current terms support the Blueprint's persistent disk configuration, and
  whether backups exist outside this repository;
- whether the Google OAuth consent screen is Testing or Production, which users
  are allowlisted, and which scopes were approved; and
- whether the finance database has been fully imported/reconciled against the
  owner's source statements and whether the static net-worth seed values remain
  representative.

Those gaps are deliberately called out rather than inferred from code or
committed sample data.
