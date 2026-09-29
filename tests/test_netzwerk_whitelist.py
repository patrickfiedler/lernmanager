"""Domain whitelist for the school firewall (/admin/netzwerk-whitelist)."""
import json
import re


def _base_domains(html):
    """The domain list the page's copy box is filled from."""
    m = re.search(r'const baseDomains = \[(.*?)\]\.concat\((.*?)\);', html)
    return json.loads('[' + m.group(1) + ']') + json.loads(m.group(2))


def test_own_domain_comes_first(as_admin):
    r = as_admin.get('/admin/netzwerk-whitelist')
    domains = _base_domains(r.get_data(as_text=True))

    # Without its own host the firewall blocks Lernmanager itself. The host
    # comes from the request (nginx forwards it); the test client's is localhost.
    assert domains[0] == 'localhost'

