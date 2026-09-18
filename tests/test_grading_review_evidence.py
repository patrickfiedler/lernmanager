"""Review evidence and reviewed report files: the review page shows what the
grader saw (document text, per-criterion source/evidence) next to the
scores, and "Dateien neu erzeugen" sends the reviewed scores to the grading
service's POST /reports. No live grading host -- urlopen is faked.
"""
import json
import os
import re

import config
import models


def _csrf_token(client):
    resp = client.get('/admin')
    return re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True)).group(1)


def _setup(job_id="job-ev"):
    klasse_id = models.create_klasse("5a")
    task_id = models.create_task("1-startklar", "desc", "lz", "MBI", "5", "pflicht")
    run_id = models.create_grading_run(job_id, klasse_id, task_id, "1-startklar", "ollama", "qwen3.6")
    return klasse_id, task_id, run_id


def _student(nachname, vorname, netzwerk_id, klasse_id=None, lernpfad=None):
    sid = models.create_student(nachname, vorname, f"u{netzwerk_id}", "pw", netzwerk_id=netzwerk_id)
    with models.db_session() as conn:
        if klasse_id:
            conn.execute("INSERT INTO student_klasse (student_id, klasse_id) VALUES (?, ?)", (sid, klasse_id))
        if lernpfad:
            conn.execute("UPDATE student SET lernpfad = ? WHERE id = ?", (lernpfad, sid))
    return sid


CRITERIA = [
    {"name": "Fachraumregeln", "score": 1, "max_score": 1, "feedback": "Alle Regeln da",
     "source": "document", "evidence": None},
    {"name": "Dateiname", "score": 2, "max_score": 2, "feedback": "Dateiname ok: startklar",
     "source": "filename", "evidence": "startklar-anna.docx"},
]
BANK = {"Fachraumregeln": {"1": "Fachraumregeln vollständig.", "0": "Es fehlen Fachraumregeln."}}


class _FakeService:
    def __init__(self, files=None, fail=False):
        self.files = files or {}
        self.fail = fail
        self.body = None

    def __call__(self, req, timeout=None):
        if self.fail:
            raise OSError("wireguard down")
        self.body = json.loads(req.data)
        payload = json.dumps({"files": self.files, "corrections_stored": 2}).encode()

        class _Resp:
            def read(self_inner):
                return payload

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return _Resp()


def _patch_service(monkeypatch, tmp_path, fake):
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(config, "GRADING_SERVICE_URL", "http://10.8.0.3:8420")
    monkeypatch.setattr(config, "GRADING_SERVICE_TOKEN", "tok")
    monkeypatch.setattr(models.urllib.request, "urlopen", fake)


def test_import_stores_document_text_evidence_and_textbausteine(db, monkeypatch):
    monkeypatch.setattr(config, "GRADING_SERVICE_URL", "")
    _, _, run_id = _setup()
    _student("Mueller", "Anna", "mueller.anna")

    models.import_grading_callback(
        "job-ev", "ollama", "qwen3.6", "2026-09-13T20:00:00",
        students=[{"student_id": "mueller.anna", "total_score": 3, "max_score": 3,
                   "document_text": "Anna Müller, 5a\nRegel 1 ...", "criteria": CRITERIA}],
        rubric="1-startklar", textbausteine=BANK,
    )

    result = models.list_grading_results(run_id)[0]
    assert result["document_text"].startswith("Anna Müller")
    assert result["criteria"][1]["source"] == "filename"
    assert result["criteria"][1]["evidence"] == "startklar-anna.docx"
    assert result["criteria"][0]["teacher_feedback"] == ""
    assert models.get_grading_run(run_id)["textbausteine"] == BANK


def test_purge_clears_document_text(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(config, "GRADING_SERVICE_URL", "")
    _, task_id, run_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, sid, "mueller.anna", CRITERIA,
                                              document_text="Anna Müller")

    models.purge_grading_run_media(run_id)

    assert models.get_grading_result(result_id)["document_text"] is None


def test_reviewed_grading_students_carry_teacher_values(db):
    klasse_id, task_id, run_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna", klasse_id=klasse_id, lernpfad="seilbahn")
    gone = _student("Weg", "Wer", "weg.wer")
    nosub = _student("Niemand", "Da", "niemand.da")
    result_id = models.create_grading_result(run_id, task_id, sid, "mueller.anna", CRITERIA)
    discarded = models.create_grading_result(run_id, task_id, gone, "weg.wer", CRITERIA)
    models.discard_grading_result(discarded)
    models.create_grading_result(run_id, task_id, nosub, "niemand.da", [],
                                  document_file=None, error="No document files found")

    criteria = models.get_grading_result(result_id)["criteria"]
    criteria[0]["teacher_score"] = 0
    criteria[1]["teacher_feedback"] = "Dateiname passt, gut gemacht!"
    models.save_grading_result_review(result_id, criteria)

    students = {s["student_id"]: s for s in models.reviewed_grading_students(run_id)}

    assert set(students) == {"mueller.anna", "niemand.da"}
    anna = students["mueller.anna"]
    assert anna["display_name"] == "Anna Mueller"
    assert anna["klasse"] == "5a"
    assert anna["seilbahn"] is True
    assert anna["error"] is None
    assert anna["criteria"][0]["points"] == 0           # teacher score, not the LLM's 1
    assert anna["criteria"][1]["points"] == 2
    assert anna["criteria"][1]["teacher_feedback"] == "Dateiname passt, gut gemacht!"
    assert students["niemand.da"]["error"] == "Keine passende Datei gefunden."


def test_regenerate_writes_only_report_files(db, tmp_path, monkeypatch):
    _, task_id, run_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    models.create_grading_result(run_id, task_id, sid, "mueller.anna", CRITERIA)
    fake = _FakeService({
        "print_slips.html": "<html>neu</html>",
        "grades.csv": "Student_ID,Total_Score\n",
        "run.log": "internal",
        "../../escape.html": "nope",
    })
    _patch_service(monkeypatch, tmp_path, fake)

    ok, message = models.regenerate_grading_reports(run_id)

    assert ok
    assert "2 Korrektur(en)" in message
    assert fake.body["rubric"] == "1-startklar"
    assert fake.body["job_id"] == models.get_grading_run(run_id)["job_id"]
    assert fake.body["students"][0]["student_id"] == "mueller.anna"
    assert sorted(os.listdir(models._grading_reports_dir(run_id))) == ["grades.csv", "print_slips.html"]
    assert not os.path.exists(tmp_path / "escape.html")


def test_regenerate_keeps_old_slips_when_service_offline(db, tmp_path, monkeypatch):
    _, task_id, run_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    models.create_grading_result(run_id, task_id, sid, "mueller.anna", CRITERIA)
    _patch_service(monkeypatch, tmp_path, _FakeService(fail=True))
    os.makedirs(models._grading_reports_dir(run_id))
    old = os.path.join(models._grading_reports_dir(run_id), "print_slips.html")
    with open(old, "w") as f:
        f.write("<html>alt</html>")

    ok, message = models.regenerate_grading_reports(run_id)

    assert not ok and "nicht erreichbar" in message
    assert open(old).read() == "<html>alt</html>"


def test_corrected_count_ignores_reviews_before_the_slips(db):
    _, task_id, run_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, sid, "mueller.anna", CRITERIA)
    criteria = models.get_grading_result(result_id)["criteria"]
    criteria[0]["teacher_score"] = 0
    models.save_grading_result_review(result_id, criteria)
    reviewed_at = models.get_grading_result(result_id)["reviewed_at"]

    assert models.count_grading_results_corrected(run_id) == 1
    assert models.count_grading_results_corrected(run_id, since="2999-01-01T00:00:00") == 0  # slips newer
    assert models.count_grading_results_corrected(run_id, since=reviewed_at) == 1  # same second still warns
    assert models.count_grading_results_corrected(run_id, since="2000-01-01T00:00:00") == 1


def test_review_page_shows_evidence_and_textbausteine(app, client, as_admin):
    _, task_id, run_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    with models.db_session() as conn:
        conn.execute("UPDATE grading_run SET textbausteine_json = ? WHERE id = ?", (json.dumps(BANK), run_id))
    result_id = models.create_grading_result(run_id, task_id, sid, "mueller.anna", CRITERIA,
                                              document_text="Regel 1: Nicht rennen.")

    body = as_admin.get(f'/admin/grading-result/{result_id}/review').get_data(as_text=True)

    assert "Regel 1: Nicht rennen." in body
    assert "Nur Dateiname, ohne KI geprüft" in body
    assert "startklar-anna.docx" in body
    assert "Es fehlen Fachraumregeln." in body  # bank shipped to the page for the live preview


def test_review_save_persists_teacher_feedback(app, client, as_admin):
    _, task_id, run_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, sid, "mueller.anna", CRITERIA)

    as_admin.post(f'/admin/grading-result/{result_id}/review', data={
        "csrf_token": _csrf_token(as_admin), "action": "save",
        "teacher_score_0": "0", "teacher_feedback_0": "  Regel 3 fehlt noch.  ",
        "teacher_score_1": "2", "teacher_feedback_1": "",
    })

    criteria = models.get_grading_result(result_id)["criteria"]
    assert criteria[0]["teacher_score"] == 0
    assert criteria[0]["teacher_feedback"] == "Regel 3 fehlt noch."
    assert criteria[1]["teacher_feedback"] == ""


def test_regenerate_route_flashes_result(app, client, as_admin, monkeypatch):
    _, _, run_id = _setup()
    monkeypatch.setattr(models, "regenerate_grading_reports", lambda rid: (True, "Zettel neu erzeugt (3 Dateien)."))

    resp = as_admin.post(f'/admin/grading-run/{run_id}/berichte-neu',
                         data={"csrf_token": _csrf_token(as_admin)}, follow_redirects=True)

    assert resp.status_code == 200
    assert "Zettel neu erzeugt (3 Dateien)." in resp.get_data(as_text=True)
