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

- Queries `SERVICENOW_TABLE` (default `task`, the base table) for records
  matching the same filter as the "My Work" dashboard list:
  `(Assigned to = me OR Additional Assignee List contains me) AND Active
  = true AND Task type not in [Request, Requested Item, Group approval,
  KB Submission, Chat Queue Entry]`.
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

`additional_assignee_list` turned out to be a stock `task` table field
(not custom), and "Task type" maps to `sys_class_name`. The default query
in `sync.py` (`build_default_query`) uses the confirmed internal names:

| Dashboard "Task type" | `sys_class_name` |
|---|---|
| Request | `sc_request` |
| Requested Item | `sc_req_item` |
| Group approval | `sysapproval_group` |
| KB Submission | `kb_submission` |
| Chat Queue Entry | `chat_queue_entry` **(unconfirmed — verify before relying on it)** |

Everything except Chat Queue Entry is a well-known stock class name.
`chat_queue_entry` is a reasonable guess but Live Agent/chat tables vary
by ServiceNow version and plugin, so double check it in your instance
(System Definition > Tables, or ask your admin) before assuming it's
filtering correctly. If it's wrong, chat queue entries just won't get
excluded — nothing will error, so it's worth a quick dry-run check.

You can always bypass `build_default_query` entirely by setting
`SERVICENOW_QUERY` directly in `.env`.

## Not yet wired up

This is a standalone CLI script — nothing in `backend/server.py` calls it
automatically. Run it manually, on a cron job, or ask to have a
`/tasks/sync-servicenow` endpoint added if you'd rather trigger it from
the app itself.
