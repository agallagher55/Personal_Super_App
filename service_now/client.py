"""Minimal ServiceNow Table API client. Stdlib only (urllib)."""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class ServiceNowError(RuntimeError):
    pass


class ServiceNowClient:
    def __init__(self, config):
        self.config = config

    def _headers(self):
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if self.config.token:
            headers['Authorization'] = 'Bearer ' + self.config.token
        else:
            raw = ('%s:%s' % (self.config.user, self.config.password)).encode('utf-8')
            headers['Authorization'] = 'Basic ' + base64.b64encode(raw).decode('ascii')
        return headers

    def _request(self, method, path, params=None, body=None):
        url = self.config.base_url + path
        if params:
            url += '?' + urllib.parse.urlencode(params)

        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')
            raise ServiceNowError(
                '%s %s failed: HTTP %s\n%s' % (method, url, e.code, detail)
            ) from e
        except urllib.error.URLError as e:
            raise ServiceNowError('%s %s failed: %s' % (method, url, e.reason)) from e
        except OSError as e:
            raise ServiceNowError('%s %s failed: %s' % (method, url, e)) from e

    def get_records(self, table, query='', fields=None, limit=200, display_value='all'):
        """Fetch all records from `table` matching an encoded query, paginating as needed."""
        records = []
        offset = 0
        while True:
            params = {
                'sysparm_query': query,
                'sysparm_limit': limit,
                'sysparm_offset': offset,
                'sysparm_display_value': display_value,
            }
            if fields:
                params['sysparm_fields'] = ','.join(fields)

            result = self._request('GET', '/api/now/table/%s' % table, params=params)
            batch = result.get('result', [])
            records.extend(batch)

            if len(batch) < limit:
                break
            offset += limit

        return records

    def find_user_sys_id(self, user_name):
        result = self._request(
            'GET',
            '/api/now/table/sys_user',
            params={
                'sysparm_query': 'user_name=%s' % user_name,
                'sysparm_fields': 'sys_id,user_name,name',
                'sysparm_limit': 1,
            },
        )
        rows = result.get('result', [])
        if not rows:
            raise ServiceNowError('No sys_user found with user_name=%s' % user_name)
        return rows[0]['sys_id']
