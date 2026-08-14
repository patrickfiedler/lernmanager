"""Tests for student.netzwerk_id generation (migrate_039).

Algorithm mirrors grading-with-llm/scripts/generate_student_ids.py so
scan-folders' surname.firstname folder names resolve to the right student
without fuzzy nachname/vorname matching.
"""
import models


def test_basic_generation():
    assert models.generate_netzwerk_id("Koch", "Anna", set()) == "koch.anna"


def test_umlaut_normalization():
    assert models.generate_netzwerk_id("Schäfer", "Lüdi", set()) == "schaefe.lued"


def test_long_lastname_truncated_to_7():
    assert models.generate_netzwerk_id("Mustermann", "Maria", set()) == "musterm.mari"


def test_short_lastname_gets_more_firstname_room():
    assert models.generate_netzwerk_id("Koch", "Alexandra", set()) == "koch.alexand"


def test_collision_gets_numeric_suffix():
    existing = {"braun.clara"}
    assert models.generate_netzwerk_id("Braun", "Clara", existing) == "braun.clara2"


def test_double_collision_increments():
    existing = {"braun.clara", "braun.clara2"}
    assert models.generate_netzwerk_id("Braun", "Clara", existing) == "braun.clara3"


def test_create_student_persists_netzwerk_id(db):
    student_id = models.create_student("Test", "Schueler", "teststudent1", "pw123", netzwerk_id="test.schueler")
    with models.db_session() as conn:
        row = conn.execute("SELECT netzwerk_id FROM student WHERE id = ?", (student_id,)).fetchone()
    assert row["netzwerk_id"] == "test.schueler"


def test_create_student_without_netzwerk_id_stays_null(db):
    student_id = models.create_student("Test", "Schueler", "teststudent2", "pw123")
    with models.db_session() as conn:
        row = conn.execute("SELECT netzwerk_id FROM student WHERE id = ?", (student_id,)).fetchone()
    assert row["netzwerk_id"] is None


def test_get_existing_netzwerk_ids_excludes_null(db):
    models.create_student("Has", "Id", "hasid", "pw123", netzwerk_id="has.id")
    models.create_student("No", "Id", "noid", "pw123")
    assert models.get_existing_netzwerk_ids() == {"has.id"}
