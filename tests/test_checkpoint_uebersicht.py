"""/admin/checkpoint-uebersicht (2026-11-25): the window's numbers for one topic,
as of today. ⚑ leads to the session, ○ counts 0, Protokolle are their own block."""
import json
import re

import pytest

import models

QUIZ = {"questions": [{"id": "f1", "type": "short_answer", "text": "Frage A", "rubric": "a"},
                      {"id": "f2", "type": "short_answer", "text": "Frage B", "rubric": "b"}]}
SECTIONS = [{"id": s, "text": s} for s in ("durchfuehrung", "rechnung", "deutung",
                                            "fehlerbetrachtung", "beobachtungen",
                                            "praktische-durchfuehrung")]


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse = models.create_klasse("11z")
    task = models.create_task("3 - Energetik", "", "", "Chemie", "11", "")
    quiz = models.create_subtask(task, "### 3.2 - Quiz", reihenfolge=0, quiz_json=json.dumps(QUIZ),
                                 checkpoint_type="quiz", kern_standard_tag="kern")
    abnahme = models.create_subtask(task, "### 1.6 - Abnahme", reihenfolge=1,
                                    checkpoint_type="abnahme", kern_standard_tag="kern")
    protokoll = models.create_subtask(task, "### 3.7 - Protokoll", reihenfolge=2,
                                      checkpoint_type="protokoll",
                                      abschnitte_json=json.dumps(SECTIONS))
    adler = models.create_student("Adler", "Kim", "u1", "pw")
    models.add_student_to_klasse(adler, klasse)
    models.assign_task_to_student(adler, klasse, task)
    return {"klasse": klasse, "task": task, "quiz": quiz, "abnahme": abnahme,
            "protokoll": protokoll, "adler": adler}


def sit(data, scores):
    return models.create_checkpoint_attempt(
        data["adler"], data["quiz"], data["task"], "quiz", "kern", score=0, attempt_count=1,
        hint_count=0, quiz_snapshot_json=json.dumps(QUIZ), session_uid="s1",
        question_scores_json=json.dumps(scores))


def page(client, data):
    return client.get(f"/admin/checkpoint-uebersicht?klasse_id={data['klasse']}"
                      f"&task_id={data['task']}").get_data(as_text=True)


def teacher(data, which, scores):
    models.save_teacher_checkpoint_grades(1, models.get_subtask(data[which]), data["klasse"],
                                          "2026-11-20", {data["adler"]: {"scores": scores}})


def test_flag_links_to_the_session(data, as_admin):
    attempt = sit(data, {"0": 3, "1": None})
    models.create_checkpoint_flag(data["quiz"], 1, "student", student_id=data["adler"],
                                  checkpoint_attempt_id=attempt)
    html = page(as_admin, data)
    link = re.search(r'href="([^"]*#sitzung-%d)">⚑' % attempt, html)
    assert link and f"student_id={data['adler']}" in link.group(1)
    review = as_admin.get(link.group(1).replace("&amp;", "&")).get_data(as_text=True)
    assert f'id="sitzung-{attempt}"' in review


def test_decided_report_without_points_counts_zero(data, as_admin):
    attempt = sit(data, {"0": 3, "1": None})
    models.create_checkpoint_flag(data["quiz"], 1, "student", student_id=data["adler"],
                                  checkpoint_attempt_id=attempt, status="abgelehnt")
    html = page(as_admin, data)
    assert "○" in html
    # quiz 3 + 0, abnahme not entered (0): 3 of 9
    assert re.search(r'cu-sum">3</td>\s*<td>9</td>', html)


def test_teacher_units_link_to_entry_and_protokoll_has_its_block(data, as_admin):
    teacher(data, "abnahme", {None: 3})
    teacher(data, "protokoll", {"praktische-durchfuehrung": 3})
    html = page(as_admin, data)
    assert f"/checkpoint/{data['abnahme']}/eintragen" in html
    assert "3/18 (5 offen)" in html
    teacher(data, "protokoll", {s["id"]: 2 for s in SECTIONS} | {"durchfuehrung": 3,
                                                                  "praktische-durchfuehrung": 3})
    assert "14/18 = 11" in page(as_admin, data)


def test_both_totals_and_protokoll_outside_them(data, as_admin):
    sit(data, {"0": 3, "1": 3})
    teacher(data, "abnahme", {None: 3})
    teacher(data, "protokoll", {s["id"]: 0 for s in SECTIONS})
    html = page(as_admin, data)
    assert re.search(r'cu-sum">9</td>\s*<td>9</td>', html)      # Protokoll's zeros not in it
    assert "15,0" in html                                        # Qualität 9/9


def test_columns_line_up(data, as_admin):
    """Head and every row have the same number of columns (Protokoll block included)."""
    sit(data, {"0": 3, "1": 2})
    teacher(data, "protokoll", {"rechnung": 2})
    html = page(as_admin, data)
    table = html[html.index('<table class="cu-table">'):html.index('</table>')]
    head, body = table.split('<tbody>')
    top, second = head.split('</tr>')[:2]
    cols = sum(int((re.search(r'colspan="(\d+)"', th) or [0, 1])[1])
               for th in re.findall(r'<th\b[^>]*>', top) if not th.startswith('<thead'))
    assert cols == top.count('rowspan="2"') + second.count('<th')
    for row in body.split('</tr>')[:-1]:
        assert row.count('<td') == cols
