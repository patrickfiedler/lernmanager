"""Creating a teacher: names in, pool login suggested, credentials as PDF."""
import models


def _admin(app):
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_id"] = 1
    return client


def test_suggestion_matches_initials_and_skips_taken_logins(app):
    client = _admin(app)
    username = client.get('/admin/lehrkraefte/benutzername-vorschlag'
                          '?nachname=Bauer&vorname=Anna').get_json()['username']
    assert username not in models.get_existing_usernames()
    assert username[0] == 'a'


def test_empty_username_gets_one_from_the_pool_and_names_are_stored(app):
    client = _admin(app)
    resp = client.post('/admin/lehrkraefte/neu', data={'nachname': 'Bauer', 'vorname': 'Anna'})
    assert resp.mimetype == 'application/pdf'
    teacher = next(t for t in models.list_teachers() if t['nachname'] == 'Bauer')
    assert teacher['vorname'] == 'Anna' and teacher['username']


def test_login_taken_by_a_student_is_refused(app):
    """The login tries admin first: a teacher named like a student locks the student out."""
    client = _admin(app)
    models.create_student("Muster", "Max", "happypanda", "bacado42")
    resp = client.post('/admin/lehrkraefte/neu',
                       data={'nachname': 'Bauer', 'vorname': 'Anna', 'username': 'happypanda'})
    assert resp.status_code == 302
    assert models.list_teachers() == []


def test_student_pool_avoids_teacher_logins(app):
    models.create_admin("agilebear", "pw", role='teacher')
    assert "agilebear" in models.get_existing_usernames()
