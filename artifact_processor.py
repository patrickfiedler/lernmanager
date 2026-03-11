"""Artifact text extraction and pseudonymization for LLM feedback.

All functions operate on bytes in memory — no temp files, no disk storage.
This satisfies the DSGVO requirement that original files never persist server-side.

Supported formats: .pptx, .odp, .sb3
Future: .docx, .odt
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET


# --- .pptx extraction ---

def extract_pptx(file_bytes: bytes) -> str:
    """Extract slide text from a .pptx file. Returns one section per slide."""
    from pptx import Presentation
    prs = Presentation(io.BytesIO(file_bytes))
    sections = []
    for i, slide in enumerate(prs.slides, start=1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = para.text.strip()
                    if line:
                        texts.append(line)
        if texts:
            sections.append(f"[Folie {i}]\n" + "\n".join(texts))
    return "\n\n".join(sections)


def strip_pptx_metadata(file_bytes: bytes) -> bytes:
    """Remove author/creator/lastModifiedBy from .pptx core properties.

    .pptx files are ZIP archives. The core properties live in
    docProps/core.xml. We blank the relevant fields before any storage.
    """
    _CLEAR_TAGS = {
        '{http://purl.org/dc/elements/1.1/}creator',
        '{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as zin, \
         zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == 'docProps/core.xml':
                root = ET.fromstring(data)
                for elem in root.iter():
                    if elem.tag in _CLEAR_TAGS:
                        elem.text = ''
                data = ET.tostring(root, encoding='unicode').encode('utf-8')
            zout.writestr(item, data)
    return buf.getvalue()


# --- .odp extraction ---

def extract_odp(file_bytes: bytes) -> str:
    """Extract slide text from an .odp file (ODF Presentation).

    .odp is a ZIP archive. Text lives in content.xml under
    <presentation:page> → <draw:frame> → <draw:text-box> → <text:p> elements.
    """
    _NS = {
        'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
        'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
        'presentation': 'urn:oasis:names:tc:opendocument:xmlns:presentation:2.0',
        'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    }
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        content_xml = z.read('content.xml')

    root = ET.fromstring(content_xml)
    # Slides are <draw:page> elements inside <office:presentation>
    pages = root.findall('.//{%s}page' % _NS['draw'])
    sections = []
    for i, page in enumerate(pages, start=1):
        texts = []
        for para in page.findall('.//{%s}p' % _NS['text']):
            # Collect all text content (spans, etc.)
            line = ''.join(para.itertext()).strip()
            if line:
                texts.append(line)
        if texts:
            sections.append(f"[Folie {i}]\n" + "\n".join(texts))
    return "\n\n".join(sections)


# --- Pseudonymization ---

def anonymize(text: str, student_name: str, class_name: str = '') -> str:
    """Replace student name and class name occurrences with placeholders.

    student_name should be "Vorname Nachname" or just one name.
    Handles first name, last name, and combined forms separately.
    class_name (e.g. "5a") is replaced with [Klasse].

    If student_name is empty, name replacement is skipped.
    """
    parts = student_name.split()
    if parts:
        # Build patterns: each individual name part + both combined orders
        candidates = list(parts)
        if len(parts) >= 2:
            candidates.append(r'\s+'.join(re.escape(p) for p in parts))           # First Last
            candidates.append(r'\s+'.join(re.escape(p) for p in reversed(parts))) # Last First

        # Apply longest patterns first to avoid partial replacements
        for pattern in sorted(candidates, key=len, reverse=True):
            escaped = pattern if r'\s+' in pattern else re.escape(pattern)
            text = re.sub(r'\b' + escaped + r'\b', '[Schüler/in]', text, flags=re.IGNORECASE)

    if class_name.strip():
        for pattern in _class_name_patterns(class_name.strip()):
            text = re.sub(pattern, '[Klasse]', text, flags=re.IGNORECASE)

    return text


def _class_name_patterns(class_name: str) -> list[str]:
    """Build regex patterns for a class name, including typographic variants.

    Handles:
    - Exact match:                  "Ginkgo-Haie-Urvögel 5"
    - Hyphens/spaces interchangeable: "Ginkgo Haie Urvögel 5"
    - Without trailing grade number:  "Ginkgo-Haie-Urvögel" / "Ginkgo Haie Urvögel"
    """
    # Split on hyphens and whitespace to get tokens
    tokens = re.split(r'[\s\-]+', class_name)
    # Trailing token is the grade number if it's purely numeric
    has_grade = tokens and tokens[-1].isdigit()
    name_tokens = tokens[:-1] if has_grade else tokens
    grade_token = tokens[-1] if has_grade else None

    sep = r'[\s\-]+'  # flexible separator

    def joined(parts, include_grade=True):
        t = list(parts) + ([grade_token] if include_grade and grade_token else [])
        return r'\b' + sep.join(re.escape(p) for p in t) + r'\b'

    patterns = []
    if name_tokens:
        patterns.append(joined(name_tokens, include_grade=True))   # full name + grade
        if has_grade:
            patterns.append(joined(name_tokens, include_grade=False))  # name without grade
        # Individual compound parts (skip grade number — too common)
        for token in name_tokens:
            patterns.append(r'\b' + re.escape(token) + r'\b')
    else:
        patterns.append(r'\b' + re.escape(class_name) + r'\b')

    return patterns


# --- .docx extraction ---

def extract_docx(file_bytes: bytes) -> str:
    """Extract text from a .docx file, preserving heading structure with # markers.

    .docx is a ZIP archive. All body text lives in word/document.xml as <w:p>
    paragraphs. Headings are identified by <w:pStyle w:val="Heading1"> (English
    Word) or <w:pStyle w:val="berschrift1"> (German Word, Ü stripped in XML).
    """
    _W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    lines = []
    for para in root.iter(f'{{{_W}}}p'):
        pstyle = para.find(f'{{{_W}}}pPr/{{{_W}}}pStyle')
        style_val = pstyle.get(f'{{{_W}}}val', '') if pstyle is not None else ''
        text = ''.join(t.text or '' for t in para.iter(f'{{{_W}}}t')).strip()
        if not text:
            continue
        sl = style_val.lower()
        if sl.startswith('heading') or sl.startswith('berschrift'):
            level = min(int(''.join(c for c in style_val if c.isdigit()) or '1'), 6)
            lines.append(f"{'#' * level} {text}")
        else:
            lines.append(text)
    return '\n'.join(lines)


# --- .odt extraction ---

def extract_odt(file_bytes: bytes) -> str:
    """Extract text from an .odt document, preserving heading structure.

    .odt is a ZIP archive. Text lives in content.xml under <office:text>.
    Headings use <text:h text:outline-level="N">, paragraphs use <text:p>.
    Reference: extract_odp() above uses the same ZIP + content.xml pattern.
    Reference: extract_docx() above uses # markers for heading levels.
    """
    _NS = {
        'text':   'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
        'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    }
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        root = ET.fromstring(z.read('content.xml'))
    body = root.find('.//{%(office)s}text' % _NS)
    lines = []
    for elem in (body or []):
        tag = elem.tag.split('}')[-1]
        text = ''.join(elem.itertext()).strip()
        if not text:
            continue
        if tag == 'h':
            level = min(int(elem.get('{%(text)s}outline-level' % _NS, '1')), 6)
            lines.append(f"{'#' * level} {text}")
        elif tag == 'p':
            lines.append(text)
    return '\n'.join(lines)


# --- .sb3 (Scratch) extraction ---

# Maps Scratch opcode prefixes to readable German category names
_SB3_CATEGORIES = {
    'motion':     'Bewegung',
    'looks':      'Aussehen',
    'sound':      'Klang',
    'event':      'Ereignisse',
    'control':    'Steuerung',
    'sensing':    'Fühlen',
    'operators':  'Operatoren',
    'data':       'Variablen',
    'procedures': 'Eigene Blöcke',
    'pen':        'Malstift',
}


def _sb3_collect_opcodes(blocks: dict) -> list[str]:
    """Return a list of all unique opcodes used in a target's blocks dict."""
    seen = set()
    result = []
    for block in blocks.values():
        if not isinstance(block, dict):
            continue
        opcode = block.get('opcode', '')
        if opcode and opcode not in seen:
            seen.add(opcode)
            result.append(opcode)
    return result



def _sb3_count_scripts(blocks: dict) -> int:
    """Count top-level blocks (= scripts) in a target's blocks dict."""
    return sum(1 for b in blocks.values() if isinstance(b, dict) and b.get('topLevel', False))


def _sb3_variable_names(target: dict) -> list[str]:
    """Return variable names defined on a target (stage = global, sprite = local)."""
    return [v[0] for v in target.get('variables', {}).values() if isinstance(v, list)]


def extract_sb3(file_bytes: bytes, filename: str = '') -> str:
    """Extract a readable project summary from a Scratch .sb3 file.

    .sb3 is a ZIP archive containing project.json. We collect per-target info
    (sprite name, opcode categories, costume/sound counts, variables, script count)
    and format it as structured text for LLM checklist evaluation.

    Level 1 criteria (block presence/counts) are fully supported.
    Level 2 criteria (script ordering, pseudo-code) require a future upgrade.
    """
    import json
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        project = json.loads(z.read('project.json'))

    targets = project.get('targets', [])
    stage = next((t for t in targets if t.get('isStage', False)), None)
    sprites = [t for t in targets if not t.get('isStage', False)]
    extensions = project.get('extensions', [])

    # Header counts
    backgrounds = len(stage.get('costumes', [])) if stage else 0
    global_vars = _sb3_variable_names(stage) if stage else []
    total_scripts = sum(_sb3_count_scripts(t.get('blocks', {})) for t in targets)
    total_blocks = sum(len([b for b in t.get('blocks', {}).values() if isinstance(b, dict)])
                       for t in targets)

    header_lines = ["[Scratch-Projekt]"]
    if filename:
        header_lines.append(f"Dateiname: {filename}")
    header_lines.append(
        f"Figuren: {len(sprites)} | Skripte: {total_scripts} | "
        f"Blöcke: {total_blocks} | Hintergründe: {backgrounds}"
    )
    if global_vars:
        header_lines.append(f"Globale Variablen: {', '.join(global_vars)}")
    header_lines.append(
        f"Erweiterungen: {', '.join(extensions) if extensions else '(keine)'}"
    )
    sections = ["\n".join(header_lines)]

    for target in targets:
        name = target.get('name', 'Unbekannt')
        is_stage = target.get('isStage', False)
        costumes = len(target.get('costumes', []))
        sounds = len(target.get('sounds', []))
        opcodes = _sb3_collect_opcodes(target.get('blocks', {}))
        local_vars = _sb3_variable_names(target) if not is_stage else []
        scripts = _sb3_count_scripts(target.get('blocks', {}))

        label = "Bühne" if is_stage else f"Figur: {name}"
        used = [_SB3_CATEGORIES[p] for p in _SB3_CATEGORIES
                if any(op.startswith(p + '_') for op in opcodes)]

        lines = [f"[{label}]"]
        if is_stage:
            lines.append(f"Hintergründe: {costumes}, Töne: {sounds}")
        else:
            lines.append(f"Skripte: {scripts}, Kostüme: {costumes}, Töne: {sounds}")
        lines.append(f"Kategorien: {', '.join(used) if used else '(keine)'}")
        if local_vars:
            lines.append(f"Lokale Variablen: {', '.join(local_vars)}")

        sections.append("\n".join(lines))

    return '\n\n'.join(sections)


# --- Format dispatch ---

ACCEPTED_FORMATS = {
    '.pptx': extract_pptx,
    '.odp':  extract_odp,
    '.docx': extract_docx,
    '.odt':  extract_odt,
    '.sb3':  extract_sb3,
}


def extract_artifact(file_bytes: bytes, filename: str) -> str:
    """Extract text from a supported artifact file. Raises ValueError for unknown formats."""
    ext = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ACCEPTED_FORMATS:
        raise ValueError(f"Unsupported format: {ext!r}. Accepted: {', '.join(ACCEPTED_FORMATS)}")
    if ext == '.sb3':
        return extract_sb3(file_bytes, filename)
    return ACCEPTED_FORMATS[ext](file_bytes)
