"""check_filename() names the file the student should end up with.

The message used to say „meine-fachraumregeln" sein (ohne Dateiendung),
gefunden: „01_Deckblatt_Vorlage" -- students had to mentally reattach the
extension. It now shows the full target filename instead.
"""
from artifact_checker import check_filename


def test_wrong_name_shows_expected_with_uploaded_extension():
    item = check_filename("01_Deckblatt_Vorlage.docx", "meine-fachraumregeln")

    assert item["passed"] is False
    assert item["note"] == 'Der Dateiname sollte „meine-fachraumregeln.docx" sein.'
    assert item["criterion"] == 'Dateiname ist „meine-fachraumregeln.docx"'
    assert "ohne Dateiendung" not in item["note"]


def test_extension_follows_the_uploaded_file():
    assert '.odt" sein.' in check_filename("x.odt", "meine-fachraumregeln")["note"]
    assert '.docx" sein.' in check_filename("x.docx", "meine-fachraumregeln")["note"]


def test_correct_name_passes():
    item = check_filename("meine-fachraumregeln.docx", "meine-fachraumregeln")

    assert item["passed"] is True
    assert item["note"] == "Der Dateiname ist korrekt."


def test_placeholders_are_substituted():
    item = check_filename("falsch.docx", "Abgabe-[Vorname]", "Alex", "Alex Muster")

    assert item["note"] == 'Der Dateiname sollte „Abgabe-Alex.docx" sein.'


def test_expected_that_already_carries_the_extension_is_not_doubled():
    item = check_filename("falsch.docx", "meine-fachraumregeln.docx")

    assert item["note"] == 'Der Dateiname sollte „meine-fachraumregeln.docx" sein.'


def test_upload_without_extension_shows_bare_name():
    item = check_filename("ohne_endung", "meine-fachraumregeln")

    assert item["note"] == 'Der Dateiname sollte „meine-fachraumregeln" sein.'


def test_source_stays_deterministic():
    assert check_filename("x.docx", "y")["source"] == "deterministic"
