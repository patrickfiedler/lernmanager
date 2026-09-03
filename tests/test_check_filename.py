"""check_filename() splits requirement from observation.

criterion = the filename the student should end up with, extension included.
note     = what their file is actually called.

The old message crammed both into the note with "(ohne Dateiendung), gefunden:";
a first attempt at simplifying put the target name in BOTH fields, so the two
lines said the same thing and the student could no longer see their own filename.
"""
from artifact_checker import check_filename


def test_wrong_name_shows_target_in_criterion_and_actual_in_note():
    item = check_filename("01_Deckblatt_Vorlage.docx", "meine-fachraumregeln")

    assert item["passed"] is False
    assert item["criterion"] == 'Dateiname enthält „meine-fachraumregeln.docx“'
    assert item["note"] == 'Deine Datei heißt „01_Deckblatt_Vorlage.docx“.'
    assert "ohne Dateiendung" not in item["note"]


def test_criterion_and_note_never_say_the_same_thing():
    item = check_filename("01_Deckblatt_Vorlage.docx", "meine-fachraumregeln")

    assert item["criterion"] != item["note"]
    # The student's own filename must survive somewhere in the feedback.
    assert "01_Deckblatt_Vorlage.docx" in item["note"]


def test_extension_follows_the_uploaded_file():
    assert check_filename("x.odt", "meine-fachraumregeln")["criterion"].endswith('.odt“')
    assert check_filename("x.docx", "meine-fachraumregeln")["criterion"].endswith('.docx“')


def test_correct_name_passes():
    item = check_filename("meine-fachraumregeln.docx", "meine-fachraumregeln")

    assert item["passed"] is True
    assert item["note"] == "Der Dateiname ist korrekt."


def test_placeholders_are_substituted():
    item = check_filename("falsch.docx", "Abgabe-[Vorname]", "Alex", "Alex Muster")

    assert item["criterion"] == 'Dateiname enthält „Abgabe-Alex.docx“'


def test_expected_that_already_carries_the_extension_is_not_doubled():
    item = check_filename("falsch.docx", "meine-fachraumregeln.docx")

    assert item["criterion"] == 'Dateiname enthält „meine-fachraumregeln.docx“'


def test_upload_without_extension_shows_bare_name():
    item = check_filename("ohne_endung", "meine-fachraumregeln")

    assert item["criterion"] == 'Dateiname enthält „meine-fachraumregeln“'


def test_source_stays_deterministic():
    assert check_filename("x.docx", "y")["source"] == "deterministic"


# Containment, not equality (2026-09-03). Exact equality rejected two names that are
# not mistakes: a version suffix the student added on purpose, and the "(1)" a browser
# appends on a second download. The check only ever advises -- uploads are identified
# by {student_id}_{task_id} on disk, never by name -- so a false "wrong name" costs
# trust and buys nothing.
def test_version_suffix_passes():
    item = check_filename("1-startklar_v2.docx", "1-startklar")

    assert item["passed"] is True


def test_browser_duplicate_suffix_passes():
    assert check_filename("1-startklar (1).docx", "1-startklar")["passed"] is True


def test_prefix_before_the_expected_name_passes():
    assert check_filename("MBI_1-startklar.docx", "1-startklar")["passed"] is True


def test_a_genuinely_different_name_still_fails():
    item = check_filename("01_Deckblatt_Vorlage.docx", "1-startklar")

    assert item["passed"] is False


def test_expected_authored_with_extension_still_matches_the_stem():
    """conventions.md says author a stem, but one carrying the extension used to fail
    against a filename it otherwise matched exactly."""
    assert check_filename("meine-fachraumregeln.docx", "meine-fachraumregeln.docx")["passed"] is True
