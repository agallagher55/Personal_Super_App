#!/usr/bin/env python3
"""Static file server for the Personal Tasks tracker.

Serves the same files `python3 -m http.server` would, plus a
GET /tasks/new (the new-task form page) and a
POST /tasks/new (appends a task to data/tasks.json and saves it to disk).

Data is stored on disk as three normalized tables that mirror the shape
this app will eventually use in a real database:

  data/sections.json  - one row per task category (id, label, slug, note)
  data/tasks.json      - one row per task (section_id foreign key)
  data/tags.json        - one row per tag (task_id foreign key)

GET /tasks.json joins them back into the nested shape the frontend expects,
the same way a database query/view would.

data/tasks.json's columns mirror a Notion-style tasks database: desc (Task),
status/done (Status), priority (Priority), due_date (Due Date), completed
(Completion Date), modified (Last edited time), note/notes (Notes),
ticket_number (TASK), time_estimate (Time Estimate), related_files (Related
Files), and parent_id (Parent item - a task's sub-items are just the other
tasks whose parent_id points back at it). assignment_group and requested_by
are this app's own additions on top of that shape, for ServiceNow-sourced
tasks. work_type/env_dev/env_qa/env_prod/cmdb_updated are Work Tasks
(section_id == WORK_SECTION_ID) -only sub-attributes: work_type classifies
the kind of work ('new-feature', 'schema-change', or '' for neither - a
task is at most one, never both); the env_* flags track which environments
it has shipped to, shown once work_type is set; cmdb_updated tracks the
CMDB update new-feature tasks specifically require.
"""

import json
import os
import re
import sys
import uuid
import http.server
import socketserver
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get('PORT', 8000))
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SECTIONS_FILE = os.path.join(DATA_DIR, 'sections.json')
TASKS_FILE = os.path.join(DATA_DIR, 'tasks.json')
TAGS_FILE = os.path.join(DATA_DIR, 'tags.json')
# Mirrors the Notion "Weekly Tasks" database's Status options (Not started,
# In progress, Pending, Done, Cancelled), keeping this app's existing
# open/in-progress/done names for the three states it already had.
STATUSES = ('open', 'in-progress', 'pending', 'done', 'cancelled')
PRIORITIES = ('low', 'medium', 'high')

# Work Tasks is the only section that gets the work_type sub-attribute
# (and, in turn, the dev/qa/prod environment checkboxes the frontend shows
# once it's set). A task is at most one of these, never both, hence radio
# buttons in the UI rather than independent checkboxes.
WORK_SECTION_ID = 'own-tasks'
WORK_TYPES = ('new-feature', 'schema-change')
ENVIRONMENTS = ('dev', 'qa', 'prod')

# The ported Personal Health app (see fitness/ARCHITECTURE.md) lives at
# backend/fitness/ as its own flat-import module set (config.py, auth.py,
# http_client.py, google_health_client.py, store.py, sync.py, api.py) -
# same style as the rest of this stdlib-only backend, just namespaced into
# its own directory. Adding it to sys.path lets `import api as fitness_api`
# resolve, and lets that module's own `import store` / `import sync` resolve
# in turn.
FITNESS_DIR = os.path.join(BASE_DIR, 'backend', 'fitness')
if FITNESS_DIR not in sys.path:
    sys.path.insert(0, FITNESS_DIR)
import api as fitness_api

FITNESS_PAGES = (
    'steps', 'heart-rate', 'sleep', 'activity', 'spo2', 'hrv',
    'breathing-rate', 'temperature', 'weight',
)

SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')


def slugify(text):
    slug = re.sub(r'[^a-z0-9]+', '-', text.strip().lower()).strip('-')
    return slug


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def format_sentence(text):
    """Capitalize each sentence and ensure the text ends with punctuation."""
    text = text.strip()
    if not text:
        return text

    sentences = []
    for sentence in SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if sentence:
            sentences.append(sentence[0].upper() + sentence[1:])
    text = ' '.join(sentences)

    if text and text[-1] not in '.!?':
        text += '.'
    return text


def load_json(path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except OSError:
        return default


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')


def load_sections():
    return load_json(SECTIONS_FILE, [])


def load_tasks():
    return load_json(TASKS_FILE, [])


def load_tags():
    return load_json(TAGS_FILE, [])


def save_sections(sections):
    save_json(SECTIONS_FILE, sections)


def save_tasks(tasks):
    save_json(TASKS_FILE, tasks)


def save_tags(tags):
    save_json(TAGS_FILE, tags)


def reposition_section(tasks, section_id):
    """Renumber the 'position' field of a section's tasks to 0..n-1,
    keeping their current relative order."""
    section_tasks = sorted(
        (t for t in tasks if t.get('section_id') == section_id),
        key=lambda t: t.get('position', 0)
    )
    for i, task in enumerate(section_tasks):
        task['position'] = i


def build_nested():
    """Join sections + tasks + tags into the nested shape the frontend
    expects, the same way a database view would."""
    sections = load_sections()
    tasks = load_tasks()
    tags = load_tags()

    tags_by_task = {}
    for tag in sorted(tags, key=lambda t: t.get('position', 0)):
        tags_by_task.setdefault(tag['task_id'], []).append({
            'text': tag['text'],
            'flag': bool(tag.get('flag'))
        })

    tasks_by_section = {}
    for task in tasks:
        tasks_by_section.setdefault(task.get('section_id'), []).append(task)
    for section_tasks in tasks_by_section.values():
        section_tasks.sort(key=lambda t: t.get('position', 0))

    result_sections = []
    for section in sections:
        nested_tasks = []
        for task in tasks_by_section.get(section['id'], []):
            nested_task = {k: v for k, v in task.items() if k not in ('section_id', 'position')}
            nested_task['tags'] = tags_by_task.get(task['id'], [])
            nested_tasks.append(nested_task)

        nested_section = {
            'id': section['id'],
            'label': section['label'],
            'slug': section['slug'],
            'tasks': nested_tasks
        }
        if section.get('note'):
            nested_section['note'] = section['note']
        result_sections.append(nested_section)

    return {'sections': result_sections}


class TaskHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/tasks/new':
            self.path = '/html/new-task.html'
            return super().do_GET()
        if path == '/tasks/new-category':
            self.path = '/html/new-category.html'
            return super().do_GET()
        if path == '/new':
            self.send_response(302)
            self.send_header('Location', '/tasks/new')
            self.end_headers()
            return
        if path == '/':
            self.path = '/html/index.html'
            return super().do_GET()
        if path == '/tasks.json':
            return self.serve_tasks_json()
        if path == '/tasks':
            self.path = '/html/tasks-index.html'
            return super().do_GET()
        if path == '/fitness':
            self.path = '/html/fitness/index.html'
            return super().do_GET()
        if path.startswith('/fitness/api/'):
            return self.handle_fitness_api_get(path, parsed)
        if path.startswith('/fitness/'):
            page = path[len('/fitness/'):]
            if page in FITNESS_PAGES:
                self.path = '/html/fitness/pages/' + page + '.html'
                return super().do_GET()
            self.send_error(404, 'Unknown fitness page: ' + page)
            return
        if path == '/finance':
            self.path = '/html/finance.html'
            return super().do_GET()
        if path.startswith('/tasks/'):
            slug = path[len('/tasks/'):]
            if self.section_slug_exists(slug):
                self.path = '/html/index.html'
                return super().do_GET()
            self.send_error(404, 'Unknown task category: ' + slug)
            return
        if path.startswith('/task/'):
            task_id = path[len('/task/'):]
            if self.find_task(task_id) is not None:
                self.path = '/html/task-detail.html'
                return super().do_GET()
            self.send_error(404, 'Unknown task: ' + task_id)
            return

        return super().do_GET()

    def section_slug_exists(self, slug):
        return any(s.get('slug') == slug for s in load_sections())

    def find_task(self, task_id):
        for task in load_tasks():
            if task.get('id') == task_id:
                return task
        return None

    def handle_fitness_api_get(self, path, parsed):
        query = parse_qs(parsed.query)
        sub = path[len('/fitness/api/'):]
        if sub == 'health':
            status, body = fitness_api.health()
        elif sub == 'metrics':
            status, body = fitness_api.metrics_summary(query)
        elif sub.startswith('metrics/') and sub.endswith('/samples'):
            metric = sub[len('metrics/'):-len('/samples')]
            status, body = fitness_api.metric_samples(metric, query)
        elif sub.startswith('metrics/'):
            metric = sub[len('metrics/'):]
            status, body = fitness_api.metric_detail(metric, query)
        else:
            status, body = 404, {'error': 'not found'}
        self.send_fitness_json(status, body)

    def send_fitness_json(self, status, body):
        payload = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_tasks_json(self):
        body = json.dumps(build_nested(), indent=2).encode('utf-8')

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/fitness/api/sync':
            status, body = fitness_api.trigger_sync()
            self.send_fitness_json(status, body)
            return
        if parsed.path == '/tasks/new':
            return self.handle_new_task()
        if parsed.path == '/tasks/new-category':
            return self.handle_new_category()
        if parsed.path == '/tasks/update':
            return self.handle_update_tasks()
        if parsed.path == '/tasks/delete':
            return self.handle_delete_task()
        self.send_error(404, 'Not found')

    def handle_new_task(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')
        fields = parse_qs(body)

        section_id = fields.get('section', [''])[0]
        desc = format_sentence(fields.get('desc', [''])[0])
        note = format_sentence(fields.get('note', [''])[0])
        tags_raw = fields.get('tags', [''])[0].strip()
        flag_tag = fields.get('flag_tag', [''])[0].strip()
        priority = fields.get('priority', ['medium'])[0].strip()
        if priority not in PRIORITIES:
            priority = 'medium'
        done = 'done' in fields
        ticket_number = fields.get('ticket_number', [''])[0].strip()
        assignment_group = fields.get('assignment_group', [''])[0].strip()
        requested_by = fields.get('requested_by', [''])[0].strip()
        due_date = fields.get('due_date', [''])[0].strip()
        time_estimate = fields.get('time_estimate', [''])[0].strip()
        related_files = fields.get('related_files', [''])[0].strip()
        parent_id = fields.get('parent_id', [''])[0].strip()
        work_type = fields.get('work_type', [''])[0].strip()
        if section_id != WORK_SECTION_ID or work_type not in WORK_TYPES:
            work_type = ''

        if not section_id or not desc:
            self.send_error(400, 'Section and description are required')
            return

        sections = load_sections()
        section = next((s for s in sections if s['id'] == section_id), None)
        if section is None:
            self.send_error(400, 'Unknown section: ' + section_id)
            return

        tasks = load_tasks()
        tags = load_tags()

        if parent_id and not any(t.get('id') == parent_id for t in tasks):
            parent_id = ''

        raw_tags = []
        if flag_tag:
            raw_tags.append({'text': flag_tag, 'flag': True})
        for raw_tag in tags_raw.split(','):
            raw_tag = raw_tag.strip()
            if raw_tag:
                raw_tags.append({'text': raw_tag, 'flag': False})

        created = now_iso()
        task_id = uuid.uuid4().hex[:12]
        position = sum(1 for t in tasks if t.get('section_id') == section_id)
        new_task = {
            'id': task_id,
            'section_id': section_id,
            'position': position,
            'desc': desc,
            'note': note,
            'notes': '',
            'status': 'done' if done else 'open',
            'done': done,
            'priority': priority,
            'ticket_number': ticket_number,
            'assignment_group': assignment_group,
            'requested_by': requested_by,
            'due_date': due_date,
            'time_estimate': time_estimate,
            'related_files': related_files,
            'parent_id': parent_id,
            'work_type': work_type,
            'env_dev': False,
            'env_qa': False,
            'env_prod': False,
            'cmdb_updated': False,
            'created': created,
            'modified': created,
            'completed': created if done else ''
        }
        tasks.append(new_task)

        for tag_position, tag in enumerate(raw_tags):
            tags.append({
                'id': uuid.uuid4().hex[:12],
                'task_id': task_id,
                'position': tag_position,
                'text': tag['text'],
                'flag': tag['flag']
            })

        save_tasks(tasks)
        save_tags(tags)

        self.send_response(303)
        self.send_header('Location', '/?added=1')
        self.end_headers()

    def handle_new_category(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')
        fields = parse_qs(body)

        label = fields.get('label', [''])[0].strip()
        if not label:
            self.send_error(400, 'Category name is required')
            return

        slug = slugify(label)
        if not slug:
            self.send_error(400, 'Category name must contain letters or numbers')
            return

        sections = load_sections()
        if any(s.get('slug') == slug or s.get('id') == slug for s in sections):
            self.send_error(400, 'A category with that name already exists')
            return

        sections.append({
            'id': slug,
            'label': label,
            'slug': slug,
            'note': ''
        })
        save_sections(sections)

        self.send_response(303)
        self.send_header('Location', '/tasks?added=1')
        self.end_headers()

    def handle_update_tasks(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')

        try:
            updates = json.loads(body)
        except ValueError:
            self.send_json_error(400, 'Invalid JSON body')
            return

        if not isinstance(updates, list):
            self.send_json_error(400, 'Expected a JSON list of task updates')
            return

        updates_by_id = {}
        order_index = {}
        for item in updates:
            task_id = item.get('id')
            if task_id:
                updates_by_id[task_id] = item
                order_index.setdefault(task_id, len(order_index))

        tasks = load_tasks()
        tags = load_tags()

        updated_count = 0
        now = now_iso()
        touched_sections = set()
        for task in tasks:
            update = updates_by_id.get(task.get('id'))
            if update is None:
                continue

            changed = False

            if 'desc' in update:
                new_desc = (update['desc'] or '').strip()
                if new_desc and new_desc != task.get('desc'):
                    task['desc'] = new_desc
                    changed = True

            if 'note' in update:
                new_note = update['note'] if isinstance(update['note'], str) else ''
                if new_note != task.get('note', ''):
                    task['note'] = new_note
                    changed = True

            if 'tags' in update and isinstance(update['tags'], list):
                new_tags = []
                for tag in update['tags']:
                    if isinstance(tag, dict) and str(tag.get('text', '')).strip():
                        new_tags.append({
                            'text': str(tag['text']).strip(),
                            'flag': bool(tag.get('flag'))
                        })
                existing_tags = sorted(
                    (t for t in tags if t.get('task_id') == task['id']),
                    key=lambda t: t.get('position', 0)
                )
                existing_simple = [{'text': t['text'], 'flag': bool(t.get('flag'))} for t in existing_tags]
                if new_tags != existing_simple:
                    tags = [t for t in tags if t.get('task_id') != task['id']]
                    for tag_position, tag in enumerate(new_tags):
                        tags.append({
                            'id': uuid.uuid4().hex[:12],
                            'task_id': task['id'],
                            'position': tag_position,
                            'text': tag['text'],
                            'flag': tag['flag']
                        })
                    changed = True

            if 'notes' in update and update['notes'] != task.get('notes', ''):
                task['notes'] = update['notes']
                changed = True

            if 'status' in update:
                new_status = update['status']
                if new_status not in STATUSES:
                    new_status = 'done' if task.get('done') else 'open'
                if new_status != task.get('status'):
                    task['status'] = new_status
                    task['done'] = (new_status == 'done')
                    task['completed'] = now if new_status == 'done' else ''
                    changed = True

            if 'priority' in update:
                new_priority = update['priority']
                if new_priority not in PRIORITIES:
                    new_priority = task.get('priority', 'medium')
                if new_priority != task.get('priority'):
                    task['priority'] = new_priority
                    changed = True

            for field in ('ticket_number', 'assignment_group', 'requested_by', 'due_date',
                          'time_estimate', 'related_files'):
                if field in update:
                    new_value = update[field].strip() if isinstance(update[field], str) else ''
                    if new_value != task.get(field, ''):
                        task[field] = new_value
                        changed = True

            if 'parent_id' in update:
                new_parent_id = update['parent_id'].strip() if isinstance(update['parent_id'], str) else ''
                if new_parent_id == task.get('id'):
                    new_parent_id = ''
                elif new_parent_id and not any(t.get('id') == new_parent_id for t in tasks):
                    new_parent_id = ''
                if new_parent_id != task.get('parent_id', ''):
                    task['parent_id'] = new_parent_id
                    changed = True

            if 'work_type' in update:
                new_work_type = update['work_type'] if isinstance(update['work_type'], str) else ''
                if new_work_type not in WORK_TYPES or task.get('section_id') != WORK_SECTION_ID:
                    new_work_type = ''
                if new_work_type != task.get('work_type', ''):
                    task['work_type'] = new_work_type
                    changed = True

            for env in ENVIRONMENTS:
                field = 'env_' + env
                if field in update:
                    new_value = bool(update[field])
                    if new_value != bool(task.get(field, False)):
                        task[field] = new_value
                        changed = True

            if 'cmdb_updated' in update:
                new_value = bool(update['cmdb_updated'])
                if new_value != bool(task.get('cmdb_updated', False)):
                    task['cmdb_updated'] = new_value
                    changed = True

            if changed:
                task['modified'] = now

            touched_sections.add(task.get('section_id'))
            updated_count += 1

        # order_index reflects drag-and-drop reordering: the frontend's
        # "Save Changes" always submits every task currently rendered on the
        # page, in the section's intended new order. Only reposition a
        # section when the payload actually covers all of its tasks -
        # otherwise (e.g. task-detail.js saving a single task) order_index
        # only knows about that one task and would wrongly shove it to the
        # front of its section.
        for section_id in touched_sections:
            section_tasks = [t for t in tasks if t.get('section_id') == section_id]
            if not all(t.get('id') in updates_by_id for t in section_tasks):
                continue
            section_tasks.sort(
                key=lambda t: order_index.get(t.get('id'), len(order_index))
            )
            for i, task in enumerate(section_tasks):
                task['position'] = i

        save_tasks(tasks)
        save_tags(tags)

        response_body = json.dumps({'status': 'ok', 'updated': updated_count}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def handle_delete_task(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')

        try:
            payload = json.loads(body)
        except ValueError:
            self.send_json_error(400, 'Invalid JSON body')
            return

        task_id = payload.get('id') if isinstance(payload, dict) else None
        if not task_id:
            self.send_json_error(400, 'Missing task id')
            return

        tasks = load_tasks()
        target = next((t for t in tasks if t.get('id') == task_id), None)
        if target is None:
            self.send_json_error(404, 'No task found with that id')
            return

        section_id = target.get('section_id')
        tasks = [t for t in tasks if t.get('id') != task_id]
        reposition_section(tasks, section_id)
        save_tasks(tasks)

        tags = load_tags()
        tags = [t for t in tags if t.get('task_id') != task_id]
        save_tags(tags)

        response_body = json.dumps({'status': 'ok', 'deleted': True}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def send_json_error(self, code, message):
        response_body = json.dumps({'status': 'error', 'message': message}).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)


class TaskServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    os.chdir(BASE_DIR)
    with TaskServer(('', PORT), TaskHandler) as httpd:
        print('Serving at http://localhost:%d' % PORT)
        httpd.serve_forever()


if __name__ == '__main__':
    main()
