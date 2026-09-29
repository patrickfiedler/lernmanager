"""The artifact check's timeouts must stay ordered: LLM < nginx < waitress.

If nginx gives up first, the student gets a raw 504 instead of the app's own
"KI-Feedback nicht verfügbar" page. The nginx and waitress values are not
copied into config.py (one source each); this test reads them where they live.
Replaced a startup warning that compared against a copy in .env (2026-09-29).
Note: the server's nginx file is edited by hand; keep the template in sync.
"""
import os
import re

import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_llm_artifact_timeout_below_nginx_below_waitress():
    nginx = _read('deploy/lernmanager.nginx.conf')
    app_block = nginx[nginx.index('location / {'):]
    nginx_read = int(re.search(r'proxy_read_timeout\s+(\d+)s;', app_block).group(1))
    waitress = int(re.search(r'channel_timeout=(\d+)', _read('run.py')).group(1))

    assert config.LLM_ARTIFACT_TIMEOUT < nginx_read < waitress
