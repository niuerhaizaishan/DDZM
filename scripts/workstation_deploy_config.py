"""Private deployment settings shared by local workstation maintenance commands."""
import os
import shlex
from pathlib import Path


def database_url(env_file=None):
    if os.environ.get('DZMM_DATABASE_URL'):
        return os.environ['DZMM_DATABASE_URL']
    path = Path(env_file or '/etc/dzmm/dzmm.env')
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            parts = shlex.split(line, comments=True)
            if parts[:1] == ['export']:
                parts = parts[1:]
            if parts and parts[0].startswith('DZMM_DATABASE_URL='):
                value = parts[0].split('=', 1)[1]
                if value:
                    return value
    raise ValueError('Set DZMM_DATABASE_URL or pass a private --env-file')
