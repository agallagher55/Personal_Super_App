# ServiceNow sync

Pulls your assigned ServiceNow tasks into `data/tasks.json` via the
[Table API](https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI),
so the "Work Tasks" list at `/tasks/work` can be kept in sync with the
Halifax ServiceNow GIS dashboard instead of copying tasks over by hand.

Instance: `halifaxprod.service-now.com` (from the dashboard URL you're
tracking: `.../now/nav/ui/classic/params/target/%24pa_dashboard.do...`).

Stdlib only — no `requests`/`pip install` needed, matches the rest of
this repo (`backend/server.py` is also pure stdlib).

## Setup

1. Copy the env template and fill it in:
   ```
   cp service_now/.env.example service_now/.env
   ```
2. Pick an auth method:
   - **Basic auth** (`SERVICENOW_USER` / `SERVICENOW_PASSWORD`) — quickest to
     get going with your own login, but ties the script to your password and
     to whatever MFA/session policy your account has. Fine for a personal,
     local-only script; don't commit `.env` (it's already git-ignored).
   - **OAuth bearer token** (`SERVICENOW_TOKEN`) — the safer option if your
     ServiceNow admin can register an Application Registry
     (`System OAuth > Application Registry`) for you and issue a token. Ask
     your Halifax ServiceNow admin whether this is already available before
     assuming personal Basic auth is the only route — some instances block
     Basic auth entirely.
3. Run a dry run first to confirm the query and field mapping look right
   without touching `data/tasks.json`:
   ```
   python3 service_now/sync.py --dry-run
   ```
4. Once it looks right, run for real:
   ```
   python3 service_now/sync.py
   ```

The first run resolves your `sys_id` from `SERVICENOW_USER` and prints it —
paste it into `SERVICENOW_USER_SYS_ID` in `.env` to skip that lookup on
future runs.

## What it does

- Queries `SERVICENOW_TABLE` (default `sc_task`, i.e. Catalog Task — the
  table your `TASK03291xx` records live in) for records where
  `assigned_to` is you and `active=true`.
- Maps each record onto the app's task schema:

  | ServiceNow field | App field |
  |---|---|
  | `number` | `ticket_number` |
  | `short_description` | `desc` |
  | `description` | `note` |
  | `assignment_group` | `assignment_group` |
  | `opened_by` | `requested_by` |
  | `due_date` | `due_date` |
  | `state` | `status` (Open → open, Work in Progress → in-progress, Closed * → done) |
  | `sys_id` | `servicenow_sys_id` (used to match on re-sync) |

- Upserts into the section given by `SERVICENOW_SECTION_ID` (default
  `own-tasks`, i.e. `/tasks/work`) — matched by `servicenow_sys_id` first,
  falling back to `ticket_number`, so re-running never creates duplicates
  and never touches the `notes` field you've typed in the app yourself.

## Known limitation

The dashboard's "My Work" list filters on `Additional Assignee List
CONTAINS Alex Gallagher` and excludes several task types (Request,
Requested Item, Group Approval, KB Submission, Chat Queue Entry) — those
look like they query the base `task` table across multiple record types,
and the "Additional Assignee List" field name isn't a stock ServiceNow
field, so it's likely a custom field in the Halifax instance. Rather than
guess at the real field/table names, this script defaults to a simpler
`assigned_to=<you>^active=true` query against `sc_task` only. Once you
confirm the actual field name (check the list's filter breadcrumb or ask
your ServiceNow admin), set `SERVICENOW_QUERY` in `.env` to an encoded
query that matches the dashboard exactly, e.g.:

```
SERVICENOW_QUERY=assigned_to=<sys_id>^ORu_additional_assignee_listLIKE<sys_id>^active=true^sys_class_nameNOT INrequest,sc_req_item,sysapproval_group,kb_submission
```

## Not yet wired up

This is a standalone CLI script — nothing in `backend/server.py` calls it
automatically. Run it manually, on a cron job, or ask to have a
`/tasks/sync-servicenow` endpoint added if you'd rather trigger it from
the app itself.
