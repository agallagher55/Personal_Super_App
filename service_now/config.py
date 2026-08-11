"""Loads ServiceNow connection settings from the environment.

Reads a local `.env` file in this folder (if present) without
overriding any variables already set in the real environment, then
exposes everything through the Config dataclass below. Stdlib only —
no python-dotenv dependency.
"""

import os
from dataclasses import dataclass

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(THIS_DIR, '.env')


def load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


load_dotenv(ENV_FILE)


@dataclass
class Config:
    instance: str
    user: str
    password: str
    token: str
    user_sys_id: str
    table: str
    query: str
    section_id: str

    @property
    def base_url(self):
        return 'https://' + self.instance


def load_config():
    instance = os.environ.get('SERVICENOW_INSTANCE', '').strip()
    if not instance:
        raise SystemExit(
            'SERVICENOW_INSTANCE is not set. Copy service_now/.env.example to '
            'service_now/.env and fill it in, or export the variables directly.'
        )

    token = os.environ.get('SERVICENOW_TOKEN', '').strip()
    user = os.environ.get('SERVICENOW_USER', '').strip()
    password = os.environ.get('SERVICENOW_PASSWORD', '').strip()

    if not token and not (user and password):
        raise SystemExit(
            'No credentials found. Set SERVICENOW_TOKEN, or both '
            'SERVICENOW_USER and SERVICENOW_PASSWORD, in service_now/.env.'
        )

    return Config(
        instance=instance,
        user=user,
        password=password,
        token=token,
        user_sys_id=os.environ.get('SERVICENOW_USER_SYS_ID', '').strip(),
        table=os.environ.get('SERVICENOW_TABLE', 'sc_task').strip(),
        query=os.environ.get('SERVICENOW_QUERY', '').strip(),
        section_id=os.environ.get('SERVICENOW_SECTION_ID', 'own-tasks').strip(),
    )
