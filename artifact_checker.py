"""Deterministic artifact gate checks — no LLM, no external services.

Called on upload when a subtask has artifact_gate_json set.
Returns {passed, message, details} — student sees message + details on failure.
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
    return {'passed': True, 'message': '', 'details': []}


def _fuzzy_match(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _result(issues: list) -> dict:
    passed = not issues
    message = "Abgabe sieht vollständig aus ✓" if passed else "Abgabe noch nicht vollständig"
    return {'passed': passed, 'message': message, 'details': issues}


def _check_presentation(file_bytes: bytes, ext: str, config: dict) -> dict:
    """Check slide count, required titles (fuzzy), and min chars per slide.

    config keys:
      format (list[str]) — accepted extensions, checked by caller
      min_slides (int)
      required_slide_titles (list[str])
      title_match_threshold (float) — fuzzy ratio, default 0.6
      min_chars_per_slide (int)
    """
    issues = []
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
            return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige .odp-Datei']}

        pages = root.findall('.//draw:page', NS)
        slide_count = len(pages)
        if slide_count < config.get('min_slides', 0):
            issues.append(f"Zu wenig Folien ({slide_count}, erwartet: {config['min_slides']})")

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
            return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige .pptx-Datei']}

        slides = prs.slides
        slide_count = len(slides)
        if slide_count < config.get('min_slides', 0):
            issues.append(f"Zu wenig Folien ({slide_count}, erwartet: {config['min_slides']})")

        titles = [slide.shapes.title.text if slide.shapes.title else '' for slide in slides]
        for req in config.get('required_slide_titles', []):
            if max((_fuzzy_match(req, t) for t in titles), default=0) < threshold:
                issues.append(f'Folie fehlt: „{req}"')

        min_chars = config.get('min_chars_per_slide', 0)
        if min_chars:
            for i, slide in enumerate(slides, 1):
                text = ' '.join(s.text for s in slide.shapes if hasattr(s, 'text')).strip()
                if len(text) < min_chars:
                    issues.append(f"Folie {i} hat zu wenig Text ({len(text)} Zeichen, erwartet: {min_chars})")

    return _result(issues)


def _check_document(file_bytes: bytes, ext: str, config: dict) -> dict:
    """Check required headings (fuzzy) and minimum word count.

    config keys:
      format (list[str]) — accepted extensions, checked by caller
      min_words (int)
      required_headings (list[str])
      title_match_threshold (float) — fuzzy ratio, default 0.6
    """
    import artifact_processor
    try:
        extracted = artifact_processor.extract_docx(file_bytes) if ext == '.docx' else artifact_processor.extract_odt(file_bytes)
    except Exception:
        return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige Datei']}

    issues = []
    threshold = config.get('title_match_threshold', 0.6)
    min_words = config.get('min_words', 0)
    if min_words:
        word_count = len(extracted.split())
        if word_count < min_words:
            issues.append(f"Zu wenig Text ({word_count} Wörter, erwartet: {min_words})")

    heading_texts = [l.lstrip('#').strip() for l in extracted.splitlines() if l.startswith('#')]
    for req in config.get('required_headings', []):
        if max((_fuzzy_match(req, h) for h in heading_texts), default=0) < threshold:
            issues.append(f'Abschnitt fehlt: „{req}"')

    return _result(issues)


def _check_scratch(file_bytes: bytes, config: dict) -> dict:
    """Check sprite count and script count in a .sb3 project."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            project = json.loads(z.read('project.json'))
    except Exception:
        return {'passed': False, 'message': 'Datei konnte nicht gelesen werden', 'details': ['Ungültige .sb3-Datei']}

    issues = []
    sprites = [t for t in project.get('targets', []) if not t.get('isStage')]

    if len(sprites) < config.get('min_sprites', 0):
        issues.append(f"Zu wenig Figuren ({len(sprites)}, erwartet: {config['min_sprites']})")

    script_count = sum(
        sum(1 for b in s.get('blocks', {}).values() if isinstance(b, dict) and b.get('topLevel'))
        for s in sprites
    )
    if script_count < config.get('min_scripts', 0):
        issues.append(f"Zu wenig Skripte ({script_count}, erwartet: {config['min_scripts']})")

    return _result(issues)
