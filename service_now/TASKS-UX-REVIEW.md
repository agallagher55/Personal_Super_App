# `/tasks` + ServiceNow workflow review

**Reviewed:** 2026-09-09  
**Inputs:** the complete `/tasks` implementation in this repository and the
Halifax ServiceNow GIS Dashboard screenshot supplied with the review request.

## Executive recommendation

Keep ServiceNow as the system of record and make `/tasks` the **personal action
layer** on top of it. The app should answer three questions faster than the
60-row ServiceNow list can:

1. What deserves attention today?
2. What am I waiting on, and from whom?
3. What changed in ServiceNow since I last looked?

The existing app already has most of the right primitives: a ServiceNow upsert,
personal notes that the sync deliberately does not overwrite, compact status
and priority controls, categories, search, a completed area, and an autosaved
scratchpad. The next iteration should not recreate ServiceNow's table. It
should add a focused work queue, preserve provenance, and turn the scratchpad
into a low-friction daily log.

## What is working well

- **Clean ownership boundary.** ServiceNow fields (`number`, short/long
  description, group, opener, due date, state, and `sys_id`) are imported while
  the app's `notes`, priority, estimate, tags, environment checklist, and order
  remain personal. That is the right separation.
- **Safe matching.** Syncing by `sys_id`, then ticket number, makes reruns
  idempotent and avoids duplicate personal tasks.
- **Useful personal workflow fields.** Priority, estimate, parent, related
  files, work type, environments, and CMDB status contain the execution detail
  that does not belong in the source ticket.
- **Good progressive disclosure.** Task cards stay compact until expanded;
  completed work is separated and filterable.
- **Scratchpad capture is genuinely lightweight.** It is always present,
  freeform, autosaves after typing, and reports save errors.
- **The dashboard filter is already mirrored.** Assigned-to/additional-assignee,
  active-only, and excluded task classes align the import set with the visible
  “My Work” list rather than importing an unrelated table dump.

## Main opportunities

### 1. Replace “all categories collapsed” with a daily work queue

The ServiceNow screenshot is an inventory view: 60 active records, mixed task
types, old opened dates, sparse due dates, and states such as **Work in
Progress**, **Awaiting User Info**, and **Open**. `/tasks` currently organizes
the same workload primarily by category, starts all categories collapsed on the
all-tasks route, and gives every open item similar visual weight. This still
requires the user to remember where today's work lives.

Add a default **Today** view above (or instead of) the full category list:

- overdue and due today;
- manually pinned “Today” items;
- in-progress items;
- items changed by the latest ServiceNow sync;
- then the next few high-priority items.

Keep categories as the planning/archive view. “Today” must be a personal flag,
not inferred only from a ServiceNow due date—most rows in the screenshot do not
have one.

### 2. Model “waiting” instead of flattening it to open

The screenshot includes **Awaiting User Info**, but the current sync maps
`pending` to `open` and unknown states to `open`. That discards the distinction
between actionable work and blocked work. Add a `waiting` local status (or map
it to the existing `pending` status), plus optional `waiting_on` and
`follow_up_date` fields. Map ServiceNow states such as Awaiting User Info to it.

This enables a high-value **Waiting / follow up** lane and prevents blocked
tickets from crowding the “do now” queue.

### 3. Make ServiceNow provenance visible and actionable

Ticket number pills currently look like metadata but do not open the source
record. Persist or derive a ServiceNow record URL from `sys_id` and make the
ticket number a link. In the task detail, visually separate:

- **From ServiceNow (read-only):** number, state, assignment group, requester,
  source description, opened date, and last ServiceNow update;
- **My plan (editable):** priority, Today, estimate, tags, local status override,
  checklist, related files, and personal notes.

This makes it obvious what a sync will overwrite. Editing imported source
fields locally today is misleading because the next sync can replace them.

### 4. Show sync health in the product

The integration is command-line only, so `/tasks` gives no indication whether
its source data is current. Add a small status block on the Work view:

> ServiceNow · synced 14 min ago · 60 active · 3 changed · Sync now

Store a sync-run record with start/end time, result, counts, query fingerprint,
and error text. A server-side “Sync now” action is useful only if credentials
can remain server-side and the request has CSRF/auth protection; otherwise keep
the CLI/cron approach and display its last-run status.

Also reconcile absent records. The sync updates returned records but does not
close or flag a local imported task that no longer appears in the active-only
query. Mark it `source_missing` first; archive it only after a successful sync
or explicit user confirmation. Never delete its personal notes.

### 5. Evolve the scratchpad into a daily log without losing freeform speed

The sidebar says “Today's List,” but the database stores one timeless text
blob. The displayed date changes each day while yesterday's text remains,
which can make old notes look current. Store one entry per local calendar date
and automatically open today's entry. Add only three small affordances:

- previous/next-day navigation;
- **Carry unfinished lines forward** (manual, not automatic);
- convert a selected line into a personal task, preserving the original line.

Keep plain text and autosave. Do not force checkboxes, parsing, or a rich-text
editor. A subtle unsaved/saving/saved state should be persistent enough to
trust; saving on `blur`/page hide in addition to the debounce reduces the risk
of losing the last keystrokes during navigation.

### 6. Add facets tailored to the source list

The existing text search is helpful but is not a substitute for queue filters.
Add URL-backed, combinable chips for:

- Today / overdue / no due date;
- In progress / waiting / open;
- high / medium / low personal priority;
- ticket type (`INC`, `TASK`, etc.);
- assignment group;
- locally created (“no ticket”);
- changed since last sync.

URL-backed filters make useful views bookmarkable and keep browser navigation
predictable. Add sort options for personal order, due date, recently updated,
oldest opened, and priority. The very old opened dates shown in ServiceNow make
an age/staleness indicator especially useful.

### 7. Reduce save ambiguity

There are currently two save models on one page: scratchpad changes autosave,
while task-card edits require the fixed **Save Changes** button; task deletion
saves immediately. Make the distinction explicit:

- show “Saved” / “Unsaved task changes” near the task controls;
- disable the button until something changes;
- warn before navigating away with unsaved task changes;
- use optimistic concurrency (`modified`/version) so a sync cannot silently
  overwrite an open editor;
- ensure keyboard users can reorder through explicit move controls, not only
  HTML drag-and-drop.

### 8. Improve scale and information hierarchy

With 60 ServiceNow rows plus personal categories, rendering all active and
completed cards into the DOM will become noisy even when sections are visually
collapsed. Render only expanded sections, or paginate/virtualize completed
history. On the active card, prioritize:

1. personal “Today” and priority signal;
2. ticket + short description;
3. status, due/follow-up date, and age;
4. assignment/requester and secondary metadata after expansion.

Use text labels alongside color for status and urgency. Add proper buttons and
`aria-expanded` to collapsible headers; the current clickable `div` headers
and visual arrows do not provide complete keyboard semantics.

## Suggested target layout

```text
Work Tasks                    ServiceNow · synced 14m ago · 3 changed [Sync]
[Today 6] [Waiting 4] [Overdue 2] [All 60]       [Search] [Filters] [Sort]

TODAY
○ HIGH  TASK0330043  Create VW for Open Data release        due today
◐ MED   INC0151846   Open Data Portal (GIS)                 in progress

WAITING / FOLLOW UP
◷ TASK0278491  LND_finance_hansen_point  waiting on requester · Sep 11

ALL WORK (categories)
▸ Work Tasks  42 open     ▸ Personal  5 open     ▸ ...

Daily log · Wed Sep 9                 [‹ Sep 8] [Sep 10 ›]
plain freeform text...
[Carry unfinished forward] [Convert selected line to task]
```

On narrow screens, put the daily log in a collapsible drawer below the Today
queue rather than above all work; the actionable queue should remain first.

## Delivery plan

### Phase 1 — trust and triage (highest value, modest scope)

1. Fix state mapping so Awaiting User Info becomes `pending`/waiting.
2. Add `source_updated_at`, `source_opened_at`, `last_seen_at`, and sync-run
   metadata; show last sync and changed/stale badges.
3. Link ticket numbers to ServiceNow records.
4. Add Today/pinned and follow-up date fields, then make Today the default Work
   view.
5. Add dirty-state navigation protection and accessible collapse controls.

### Phase 2 — durable daily workflow

1. Change scratchpad storage from singleton to date-keyed entries.
2. Add day navigation, carry-forward, and line-to-task conversion.
3. Add URL-backed status/due/group/type facets and sorting.
4. Reconcile records absent from successful ServiceNow syncs.

### Phase 3 — polish and automation

1. Add a protected server-triggered sync or scheduled job.
2. Add conflict/version handling between web edits and sync.
3. Lazy-render large sections and paginate completed history.
4. Add a small weekly review view: completed, carried over, stale, and waiting.

## Deliberate non-goals

- Do not reproduce every ServiceNow column or build another generic table.
- Do not push personal notes, priority, or daily-plan data back to ServiceNow by
  default.
- Do not automatically delete local tasks when a source record disappears.
- Do not turn the scratchpad into a second structured task manager.
- Do not add notifications until follow-up dates and source freshness are
  trustworthy.

## Success measures

- A user can identify today's next action in under 10 seconds.
- ServiceNow freshness and last sync outcome are always visible.
- Waiting work is excluded from the actionable queue but cannot be forgotten.
- No personal notes are lost when a ticket changes or leaves the active query.
- Yesterday's scratchpad is never presented as today's entry.
- The normal morning workflow needs no manual comparison of two full lists.
