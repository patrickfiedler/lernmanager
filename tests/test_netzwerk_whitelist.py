"""Domain whitelist for the school firewall (/admin/netzwerk-whitelist)."""
import json
import re

import models


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


def test_youtube_brings_its_companions(as_admin):
    task_id = models.create_task('Videos', '', '', 'MBI', '5', 'pflicht')
    models.create_material(task_id, 'link', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    r = as_admin.get('/admin/netzwerk-whitelist')
    domains = _base_domains(r.get_data(as_text=True))

    # youtube.com alone is not enough for an embedded video to play.
    for d in ['youtube.com', 'ytimg.com', 'googlevideo.com', 'ggpht.com']:
        assert d in domains


def test_companion_already_linked_is_not_duplicated(db):
    task_id = models.create_task('Videos', '', '', 'MBI', '5', 'pflicht')
    models.create_material(task_id, 'link', 'https://youtu.be/dQw4w9WgXcQ')
    models.create_material(task_id, 'link', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    names = [d['domain'] for d in models.get_external_link_domains()]
    assert names.count('youtube.com') == 1
    assert names.count('ytimg.com') == 1
