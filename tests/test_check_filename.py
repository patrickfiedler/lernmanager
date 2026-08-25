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
    assert item["criterion"] == 'Dateiname ist „meine-fachraumregeln.docx"'
    assert item["note"] == 'Deine Datei heißt „01_Deckblatt_Vorlage.docx".'
    assert "ohne Dateiendung" not in item["note"]


def test_criterion_and_note_never_say_the_same_thing():
    item = check_filename("01_Deckblatt_Vorlage.docx", "meine-fachraumregeln")

    assert item["criterion"] != item["note"]
    # The student's own filename must survive somewhere in the feedback.
    assert "01_Deckblatt_Vorlage.docx" in item["note"]


def test_extension_follows_the_uploaded_file():
    assert check_filename("x.odt", "meine-fachraumregeln")["criterion"].endswith('.odt"')
    assert check_filename("x.docx", "meine-fachraumregeln")["criterion"].endswith('.docx"')


def test_correct_name_passes():
    item = check_filename("meine-fachraumregeln.docx", "meine-fachraumregeln")

    assert item["passed"] is True
    assert item["note"] == "Der Dateiname ist korrekt."


def test_placeholders_are_substituted():
    item = check_filename("falsch.docx", "Abgabe-[Vorname]", "Alex", "Alex Muster")

    assert item["criterion"] == 'Dateiname ist „Abgabe-Alex.docx"'


def test_expected_that_already_carries_the_extension_is_not_doubled():
    item = check_filename("falsch.docx", "meine-fachraumregeln.docx")

    assert item["criterion"] == 'Dateiname ist „meine-fachraumregeln.docx"'


def test_upload_without_extension_shows_bare_name():
    item = check_filename("ohne_endung", "meine-fachraumregeln")

    assert item["criterion"] == 'Dateiname ist „meine-fachraumregeln"'


def test_source_stays_deterministic():
    assert check_filename("x.docx", "y")["source"] == "deterministic"
