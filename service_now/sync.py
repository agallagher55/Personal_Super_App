#!/usr/bin/env python3
"""Pull ServiceNow tasks into data/tasks.json.

Usage:
    python3 service_now/sync.py [--dry-run]

Requires service_now/.env (see .env.example) with instance + credentials.
Fetches records from SERVICENOW_TABLE (default sc_task) assigned to you,
maps them onto the app's task schema, and upserts them into the section
named by SERVICENOW_SECTION_ID (matched against data/sections.json) —
matching existing tasks in data/tasks.json by ServiceNow sys_id (falling
back to ticket number) so re-running this doesn't create duplicates or
clobber notes you've added locally.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client import ServiceNowClient, ServiceNowError
from config import load_config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS_FILE = os.path.join(BASE_DIR, 'data', 'sections.json')
TASKS_FILE = os.path.join(BASE_DIR, 'data', 'tasks.json')

STATE_TO_STATUS = {
    'open': 'open',
    'pending': 'open',
    'work in progress': 'in-progress',
    'in progress': 'in-progress',
}

# sys_class_name values for the "Task type != ..." exclusions on the "My
# Work" dashboard list. Confirmed against the Halifax instance's filter
# breakdown except chat_queue_entry -- verify that one before relying on
# it (Live Agent tables vary by ServiceNow version/plugin).
EXCLUDED_TASK_TYPES = [
    'sc_request',        # Request
    'sc_req_item',        # Requested Item
    'sysapproval_group',  # Group approval
    'kb_submission',      # KB Submission
    'chat_queue_entry',   # Chat Queue Entry -- unconfirmed, double check
]


def build_default_query(user_sys_id):
    """Mirrors the "My Work" dashboard list filter:
    (Assigned to = me OR Additional Assignee List contains me)
    AND Active = true AND Task type not in [...]
    """
    parts = [
        'assigned_to=%s' % user_sys_id,
        'ORadditional_assignee_listLIKE%s' % user_sys_id,
        'active=true',
    ]
    parts += ['sys_class_name!=%s' % t for t in EXCLUDED_TASK_TYPES]
    return '^'.join(parts)


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def field(record, name):
    """sysparm_display_value=all wraps every field as {value, display_value}."""
    value = record.get(name)
    if isinstance(value, dict):
        return value.get('display_value', '') or ''
    return value or ''


def field_value(record, name):
    value = record.get(name)
    if isinstance(value, dict):
        return value.get('value', '') or ''
    return value or ''


def map_status(state_display):
    state_display = state_display.strip().lower()
    if state_display.startswith('closed') or state_display in ('complete', 'completed', 'resolved'):
        return 'done'
    return STATE_TO_STATUS.get(state_display, 'open')


def map_record(record):
    due_date_raw = field_value(record, 'due_date')
    due_date = due_date_raw.split(' ')[0] if due_date_raw else ''

    return {
        'servicenow_sys_id': field_value(record, 'sys_id'),
        'ticket_number': field(record, 'number'),
        'desc': field(record, 'short_description') or field(record, 'number'),
        'note': field(record, 'description'),
        'assignment_group': field(record, 'assignment_group'),
        'requested_by': field(record, 'opened_by'),
        'due_date': due_date,
        'status': map_status(field(record, 'state')),
    }


def load_sections():
    with open(SECTIONS_FILE, 'r') as f:
        return json.load(f)


def load_tasks():
    with open(TASKS_FILE, 'r') as f:
        return json.load(f)


def save_tasks(tasks):
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=2)
        f.write('\n')


def find_section(section_id):
    for section in load_sections():
        if section['id'] == section_id:
            return section
    raise SystemExit('No section with id=%s in data/sections.json' % section_id)


def find_existing_task(tasks, section_id, mapped):
    for task in tasks:
        if task.get('section_id') != section_id:
            continue
        if mapped['servicenow_sys_id'] and task.get('servicenow_sys_id') == mapped['servicenow_sys_id']:
            return task
        if task.get('ticket_number') and task.get('ticket_number') == mapped['ticket_number']:
            return task
    return None


def upsert(tasks, section_id, mapped, dry_run):
    existing = find_existing_task(tasks, section_id, mapped)
    now = now_iso()

    if existing is None:
        position = sum(1 for t in tasks if t.get('section_id') == section_id)
        new_task = {
            'id': uuid.uuid4().hex[:12],
            'section_id': section_id,
            'position': position,
            'desc': mapped['desc'],
            'note': mapped['note'],
            'notes': '',
            'done': mapped['status'] == 'done',
            'status': mapped['status'],
            'priority': 'medium',
            'ticket_number': mapped['ticket_number'],
            'assignment_group': mapped['assignment_group'],
            'requested_by': mapped['requested_by'],
            'due_date': mapped['due_date'],
            'servicenow_sys_id': mapped['servicenow_sys_id'],
            'created': now,
            'modified': now,
            'completed': now if mapped['status'] == 'done' else '',
        }
        if not dry_run:
            tasks.append(new_task)
        return 'created'

    changed = False
    for f in ('desc', 'note', 'assignment_group', 'requested_by', 'due_date', 'ticket_number', 'servicenow_sys_id'):
        if existing.get(f) != mapped[f]:
            existing[f] = mapped[f]
            changed = True

    if existing.get('status') != mapped['status']:
        existing['status'] = mapped['status']
        existing['done'] = mapped['status'] == 'done'
        existing['completed'] = now if mapped['status'] == 'done' else ''
        changed = True

    if changed and not dry_run:
        existing['modified'] = now

    return 'updated' if changed else 'unchanged'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help="Fetch and report, but don't write tasks.json")
    args = parser.parse_args()

    config = load_config()
    client = ServiceNowClient(config)

    if not config.user_sys_id and not config.query:
        if not config.user:
            raise SystemExit(
                'SERVICENOW_USER_SYS_ID and SERVICENOW_QUERY are both unset, and there is no '
                'SERVICENOW_USER to resolve a sys_id from. Set one of these in service_now/.env.'
            )
        print('Resolving sys_id for user_name=%s ...' % config.user)
        config.user_sys_id = client.find_user_sys_id(config.user)
        print('Found sys_id=%s -- pin this as SERVICENOW_USER_SYS_ID in service_now/.env '
              'to skip this lookup next time.' % config.user_sys_id)

    query = config.query or build_default_query(config.user_sys_id)
    print('Querying %s: %s' % (config.table, query))

    try:
        records = client.get_records(config.table, query=query)
    except ServiceNowError as e:
        raise SystemExit(str(e))

    print('Fetched %d record(s).' % len(records))

    section = find_section(config.section_id)
    tasks = load_tasks()

    counts = {'created': 0, 'updated': 0, 'unchanged': 0}
    for record in records:
        mapped = map_record(record)
        outcome = upsert(tasks, section['id'], mapped, args.dry_run)
        counts[outcome] += 1
        print('  [%s] %s - %s' % (outcome, mapped['ticket_number'] or '(no number)', mapped['desc']))

    print('created=%d updated=%d unchanged=%d' % (counts['created'], counts['updated'], counts['unchanged']))

    if args.dry_run:
        print('Dry run -- data/tasks.json was not modified.')
    else:
        save_tasks(tasks)
        print('Saved to %s' % TASKS_FILE)


if __name__ == '__main__':
    main()
