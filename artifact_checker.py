"""Deterministic artifact gate checks — no LLM, no external services.

Called on upload when a subtask has artifact_gate_json set.
Returns {passed, message, details, matches} — student sees both what's missing
and what already looks good.
"""

import io
import zipfile
import json
from difflib import SequenceMatcher


def check_gate(file_bytes: bytes, filename: str, gate_config: dict) -> dict:
    """Dispatch to format-specific check. Passes by default for unknown formats."""
    ext = ('.' + filename.rsplit('.', 1)[-1].lower()) if '.' in filename else ''
    if ext in ('.pptx', '.odp'):
        return _check_presentation(file_bytes, ext, gate_config)
    if ext in ('.docx', '.odt'):
        return _check_document(file_bytes, ext, gate_config)
    if ext == '.sb3':
        return _check_scratch(file_bytes, gate_config)
    return {'passed': True, 'message': '', 'details': [], 'matches': []}


def _fuzzy_match(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def check_filename(filename: str, expected_filename: str, student_vorname: str = '', student_name: str = '') -> dict:
    """Deterministic filename check — never sent to the LLM (see conventions.md).

    Compares the uploaded filename's stem against expected_filename with
    [Vorname]/[Name] placeholders substituted for the student's real name.
    Shaped like an LLM checklist item so it can be spliced into the same
    feedback list; the caller marks it non-LLM (e.g. source='deterministic').
    """
    stem = filename.rsplit('.', 1)[0] if '.' in filename else filename
    expected = expected_filename.replace('[Vorname]', student_vorname).replace('[Name]', student_name)
    passed = stem.strip().lower() == expected.strip().lower()
    note = (
        "Der Dateiname ist korrekt."
        if passed
        else f'Der Dateiname sollte „{expected}" sein (ohne Dateiendung), gefunden: „{stem}".'
    )
    return {'criterion': f'Dateiname ist „{expected}"', 'passed': passed, 'note': note, 'source': 'deterministic'}


def _result(issues: list, matches: list = None, warnings: list = None) -> dict:
    passed = not issues
    message = "Abgabe sieht vollständig aus ✓" if passed else "Abgabe noch nicht vollständig"
    return {'passed': passed, 'message': message, 'details': issues, 'matches': matches or [], 'warnings': warnings or []}


def _check_presentation(file_bytes: bytes, ext: str, config: dict) -> dict:
    """Check slide count, required titles (fuzzy), min chars per slide, and min images.

    config keys:
      format (list[str]) — accepted extensions, checked by caller
      min_slides (int)
      min_images (int)
      required_slide_titles (list[str])
      title_match_threshold (float) — fuzzy ratio, default 0.6
      min_chars_per_slide (int)
    """
    issues = []
    matches = []
    threshold = config.get('title_match_threshold', 0.6)

    if ext == '.odp':
        import xml.etree.ElementTree as ET
        NS = {
            'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
            'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
            'presentation': 'urn:oasis:names:tc:opendocument:xmlns:presentation:1.0',
        }
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                root = ET.fromstring(z.read('content.xml'))
        except Exception:
            return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige .odp-Datei'], 'matches': []}

        pages = root.findall('.//draw:page', NS)
        slide_count = len(pages)
        if config.get('min_slides', 0):
            if slide_count < config['min_slides']:
                issues.append(f"Zu wenig Folien ({slide_count}, erwartet: {config['min_slides']})")
            else:
                matches.append(f"{slide_count} Folien ✓")

        titles = []
        for page in pages:
            title_text = ''
            for frame in page.findall('.//draw:frame', NS):
                cls = frame.get('{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}class')
                if cls == 'title':
                    title_text = ' '.join(frame.itertext()).strip()
                    break
            titles.append(title_text)

        for req in config.get('required_slide_titles', []):
            if max((_fuzzy_match(req, t) for t in titles), default=0) < threshold:
                issues.append(f'Folie fehlt: „{req}"')
            else:
                matches.append(f'Folie gefunden: „{req}" ✓')

        min_chars = config.get('min_chars_per_slide', 0)
        if min_chars:
            for i, page in enumerate(pages, 1):
                text = ' '.join(page.itertext()).strip()
                if len(text) < min_chars:
                    issues.append(f"Folie {i} hat zu wenig Text ({len(text)} Zeichen, erwartet: {min_chars})")

    elif ext == '.pptx':
        from pptx import Presentation
        try:
            prs = Presentation(io.BytesIO(file_bytes))
        except Exception:
            return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige .pptx-Datei'], 'matches': []}

        slides = prs.slides
        slide_count = len(slides)
        if config.get('min_slides', 0):
            if slide_count < config['min_slides']:
                issues.append(f"Zu wenig Folien ({slide_count}, erwartet: {config['min_slides']})")
            else:
                matches.append(f"{slide_count} Folien ✓")

        titles = [slide.shapes.title.text if slide.shapes.title else '' for slide in slides]
        for req in config.get('required_slide_titles', []):
            if max((_fuzzy_match(req, t) for t in titles), default=0) < threshold:
                issues.append(f'Folie fehlt: „{req}"')
            else:
                matches.append(f'Folie gefunden: „{req}" ✓')

        min_chars = config.get('min_chars_per_slide', 0)
        if min_chars:
            for i, slide in enumerate(slides, 1):
                text = ' '.join(s.text for s in slide.shapes if hasattr(s, 'text')).strip()
                if len(text) < min_chars:
                    issues.append(f"Folie {i} hat zu wenig Text ({len(text)} Zeichen, erwartet: {min_chars})")

    min_images = config.get('min_images', 0)
    if min_images:
        image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.wmf', '.emf', '.svg'}
        prefix = 'Pictures/' if ext == '.odp' else 'ppt/media/'
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                image_count = sum(
                    1 for name in z.namelist()
                    if name.startswith(prefix) and ('.' + name.rsplit('.', 1)[-1].lower()) in image_exts
                )
        except Exception:
            image_count = 0
        if image_count < min_images:
            issues.append(f"Zu wenig Bilder ({image_count}, erwartet: {min_images})")
        else:
            matches.append(f"{image_count} Bild{'er' if image_count != 1 else ''} ✓")

    return _result(issues, matches)


def _check_document(file_bytes: bytes, ext: str, config: dict) -> dict:
    """Check required headings (fuzzy), minimum word count, and minimum image count.

    config keys:
      format (list[str]) — accepted extensions, checked by caller
      min_words (int)
      min_images (int)
      required_headings (list[str])
      title_match_threshold (float) — fuzzy ratio, default 0.6
    """
    import artifact_processor
    try:
        extracted = artifact_processor.extract_docx(file_bytes) if ext == '.docx' else artifact_processor.extract_odt(file_bytes)
    except Exception:
        return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige Datei']}

    issues = []
    matches = []
    warnings = []
    threshold = config.get('title_match_threshold', 0.6)
    min_words = config.get('min_words', 0)
    if min_words:
        word_count = len(extracted.split())
        if word_count < min_words:
            warnings.append("wenig Text vorhanden")
        else:
            matches.append("Wortanzahl erreicht")

    min_images = config.get('min_images', 0)
    if min_images:
        image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.wmf', '.emf', '.svg'}
        prefix = 'word/media/' if ext == '.docx' else 'Pictures/'
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                image_count = sum(
                    1 for name in z.namelist()
                    if name.startswith(prefix) and ('.' + name.rsplit('.', 1)[-1].lower()) in image_exts
                )
        except Exception:
            image_count = 0
        if image_count < min_images:
            issues.append(f"Zu wenig Bilder ({image_count}, erwartet: {min_images})")
        else:
            matches.append(f"{image_count} Bild{'er' if image_count != 1 else ''} ✓")

    heading_texts = [l.lstrip('#').strip() for l in extracted.splitlines() if l.startswith('#')]
    for req in config.get('required_headings', []):
        if max((_fuzzy_match(req, h) for h in heading_texts), default=0) < threshold:
            issues.append(f'Abschnitt fehlt: „{req}"')
        else:
            matches.append(f'Abschnitt gefunden: „{req}" ✓')

    return _result(issues, matches, warnings)


def _check_scratch(file_bytes: bytes, config: dict) -> dict:
    """Check sprite count and script count in a .sb3 project."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            project = json.loads(z.read('project.json'))
    except Exception:
        return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige .sb3-Datei']}

    issues = []
    matches = []
    sprites = [t for t in project.get('targets', []) if not t.get('isStage')]

    if config.get('min_sprites', 0):
        if len(sprites) < config['min_sprites']:
            issues.append(f"Zu wenig Figuren ({len(sprites)}, erwartet: {config['min_sprites']})")
        else:
            matches.append(f"{len(sprites)} Figuren ✓")

    script_count = sum(
        sum(1 for b in s.get('blocks', {}).values() if isinstance(b, dict) and b.get('topLevel'))
        for s in sprites
    )
    if config.get('min_scripts', 0):
        if script_count < config['min_scripts']:
            issues.append(f"Zu wenig Skripte ({script_count}, erwartet: {config['min_scripts']})")
        else:
            matches.append(f"{script_count} Skripte ✓")

    return _result(issues, matches)
