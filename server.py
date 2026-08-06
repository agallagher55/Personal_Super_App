#!/usr/bin/env python3
"""Static file server for the Personal Tasks tracker.

Serves the same files `python3 -m http.server` would, plus a
GET /tasks/new (the new-task form page) and a
POST /tasks/new (appends a task to tasks.json and saves it to disk).
"""

import json
import os
import uuid
import http.server
import socketserver
from urllib.parse import parse_qs, urlparse

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_FILE = os.path.join(BASE_DIR, 'data', 'tasks.json')


class TaskHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/tasks/new':
            self.path = '/html/new-task.html'
            return super().do_GET()
        if path == '/':
            self.path = '/html/index.html'
            return super().do_GET()
        if path == '/tasks.json':
            return self.serve_tasks_json()
        if path == '/tasks':
            self.path = '/html/tasks-index.html'
            return super().do_GET()
        if path.startswith('/tasks/'):
            slug = path[len('/tasks/'):]
            if self.section_slug_exists(slug):
                self.path = '/html/index.html'
                return super().do_GET()
            self.send_error(404, 'Unknown task category: ' + slug)
            return

        return super().do_GET()

    def section_slug_exists(self, slug):
        try:
            with open(TASKS_FILE, 'r') as f:
                data = json.load(f)
        except OSError:
            return False
        return any(s.get('slug') == slug for s in data.get('sections', []))

    def serve_tasks_json(self):
        try:
            with open(TASKS_FILE, 'rb') as f:
                body = f.read()
        except OSError:
            self.send_error(404, 'tasks.json not found')
            return

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/tasks/new':
            return self.handle_new_task()
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
        desc = fields.get('desc', [''])[0].strip()
        note = fields.get('note', [''])[0].strip()
        tags_raw = fields.get('tags', [''])[0].strip()
        flag_tag = fields.get('flag_tag', [''])[0].strip()
        done = 'done' in fields

        if not section_id or not desc:
            self.send_error(400, 'Section and description are required')
            return

        with open(TASKS_FILE, 'r') as f:
            data = json.load(f)

        section = next(
            (s for s in data.get('sections', []) if s['id'] == section_id),
            None
        )
        if section is None:
            self.send_error(400, 'Unknown section: ' + section_id)
            return

        tags = []
        if flag_tag:
            tags.append({'text': flag_tag, 'flag': True})
        for raw_tag in tags_raw.split(','):
            raw_tag = raw_tag.strip()
            if raw_tag:
                tags.append({'text': raw_tag, 'flag': False})

        new_task = {
            'id': uuid.uuid4().hex[:12],
            'desc': desc,
            'note': note,
            'notes': '',
            'tags': tags,
            'done': done
        }
        section['tasks'].append(new_task)

        with open(TASKS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')

        self.send_response(303)
        self.send_header('Location', '/?added=1')
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
        for item in updates:
            task_id = item.get('id')
            if task_id:
                updates_by_id[task_id] = item

        with open(TASKS_FILE, 'r') as f:
            data = json.load(f)

        updated_count = 0
        for section in data.get('sections', []):
            for task in section.get('tasks', []):
                update = updates_by_id.get(task.get('id'))
                if update is None:
                    continue
                if 'notes' in update:
                    task['notes'] = update['notes']
                if 'done' in update:
                    task['done'] = bool(update['done'])
                updated_count += 1

        with open(TASKS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')

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

        with open(TASKS_FILE, 'r') as f:
            data = json.load(f)

        deleted = False
        for section in data.get('sections', []):
            tasks = section.get('tasks', [])
            for i, task in enumerate(tasks):
                if task.get('id') == task_id:
                    del tasks[i]
                    deleted = True
                    break
            if deleted:
                break

        if not deleted:
            self.send_json_error(404, 'No task found with that id')
            return

        with open(TASKS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')

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


def main():
    os.chdir(BASE_DIR)
    with socketserver.TCPServer(('', PORT), TaskHandler) as httpd:
        print('Serving at http://localhost:%d' % PORT)
        httpd.serve_forever()


if __name__ == '__main__':
    main()