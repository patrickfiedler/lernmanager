"""Regression test: _get_client_ip() must not trust X-Real-IP from a direct
connection. Gates school_only materials and Chemie checkpoints on the school's
IP range -- trusting the header unconditionally lets any direct request to the
app port (bypassing nginx) spoof its way past the gate.
"""
from app import app as flask_app, _get_client_ip


def test_x_real_ip_ignored_when_not_from_loopback():
    with flask_app.test_request_context(
        '/', headers={'X-Real-IP': '10.0.0.5'}, environ_base={'REMOTE_ADDR': '203.0.113.9'}
    ):
        assert _get_client_ip() == '203.0.113.9'


def test_x_real_ip_trusted_when_from_loopback():
    with flask_app.test_request_context(
        '/', headers={'X-Real-IP': '10.0.0.5'}, environ_base={'REMOTE_ADDR': '127.0.0.1'}
    ):
        assert _get_client_ip() == '10.0.0.5'
