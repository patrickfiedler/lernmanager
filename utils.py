import re
import random
import secrets
import ipaddress
import unicodedata
from datetime import datetime


def is_ip_allowed(ip_str, ranges_str):
    """Check if ip_str is in any CIDR/IP in ranges_str (comma/newline separated). Empty ranges = allow all."""
    if not ranges_str or not ranges_str.strip():
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False
    for entry in re.split(r'[,\n]', ranges_str):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def is_within_time_window(start_str, end_str, now=None):
    """Check if now falls within HH:MM-HH:MM (wraps past midnight). Empty start/end = allow all times."""
    if not start_str or not end_str:
        return True
    now = now or datetime.now()
    start = datetime.strptime(start_str, '%H:%M').time()
    end = datetime.strptime(end_str, '%H:%M').time()
    current = now.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def format_bytes(num_bytes):
    """Human-readable size, e.g. 4200000000 -> '3.9 GB'."""
    size = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def slugify(text):
    """Convert text to URL-friendly slug. Handles German umlauts."""
    text = text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    text = text.replace('Ä', 'Ae').replace('Ö', 'Oe').replace('Ü', 'Ue')
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii').lower()
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text


def find_netzwerk_login_column(headers):
    """
    Given a CSV header row (list of strings), return the index of the column
    holding the real school network login/username, or None if none can be
    identified confidently.

    Used by parse_netzwerk_csv() below for the admin/bewertung/netzwerk-ids
    roster import (models.diff_netzwerk_ids reuses grading-with-llm's
    scripts/validate_student_ids.py mismatch-reporting approach on top of
    this). Nachname/Vorname are read positionally (row[0]/row[1]), matching
    the convention scripts/generate_student_ids.py already established for
    this school's roster exports -- only the login column is new territory,
    since that script only ever derived IDs from names, never consumed a
    real login column.
    """
    # Keyword substring match, same style as generate_student_ids.py's
    # find_mbi_tracker_column/find_kurs_column. First header containing any
    # of these (case-insensitive) wins. If your real export uses a header
    # not covered here, add it to this list -- the error message on a failed
    # upload lists the CSV's actual headers so the gap is easy to spot.
    keywords = (
        'benutzername', 'nutzername', 'login', 'kennung',
        'account', 'netzwerk-id', 'netzwerkid', 'username',
    )
    for i, header in enumerate(headers):
        h = header.strip().lower()
        if any(kw in h for kw in keywords):
            return i
    return None


def _find_exact_column(headers, name):
    """Case-insensitive exact header match, for the optional columns
    (Klasse/Klassenstufe/Seilbahn) whose names are fixed by convention in
    this school's student_mapping.csv export -- unlike the login column,
    there's no need for find_netzwerk_login_column's fuzzy keyword matching
    here, and exact matching avoids 'Klasse' accidentally matching the
    'Klassenstufe' column."""
    for i, header in enumerate(headers):
        if header.strip().lower() == name:
            return i
    return None


def parse_netzwerk_csv(file_stream):
    """
    Parse an uploaded roster CSV for the admin/bewertung/netzwerk-ids page.
    Mirrors grading-with-llm/scripts/generate_student_ids.py's
    parse_csv_roster() (flexible-ish column handling, tolerant of
    short/blank rows) but reads a real login value per row instead of
    deriving one.

    Also opportunistically picks up Klasse/Klassenstufe/Seilbahn/Kurs
    columns if present (the school's student_mapping.csv has these
    alongside the login column) -- used by
    models.diff_netzwerk_ids()/diff_klassenstufen()/diff_klassen_kurs() for
    the Lernpfad, Klassenstufe and class-group cross-checks. Any of the
    four is optional; missing ones come back as ''.

    Returns list of {'nachname', 'vorname', 'login', 'klasse',
    'klassenstufe', 'seilbahn', 'kurs'} dicts. Raises ValueError with a
    message safe to flash to the admin.
    """
    import csv
    import io

    raw = file_stream.read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV ist leer.")

    headers = rows[0]
    login_idx = find_netzwerk_login_column(headers)
    if login_idx is None:
        raise ValueError(
            f"Keine Login-Spalte in der CSV gefunden. Vorhandene Spalten: {', '.join(headers)}"
        )
    klasse_idx = _find_exact_column(headers, 'klasse')
    klassenstufe_idx = _find_exact_column(headers, 'klassenstufe')
    seilbahn_idx = _find_exact_column(headers, 'seilbahn')
    kurs_idx = _find_exact_column(headers, 'kurs')

    def cell(row, idx):
        return row[idx].strip() if idx is not None and len(row) > idx else ''

    students = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        nachname = row[0].strip()
        vorname = row[1].strip()
        login = row[login_idx].strip() if len(row) > login_idx else ''
        if not nachname or not vorname or not login:
            continue
        students.append({
            'nachname': nachname, 'vorname': vorname, 'login': login,
            'klasse': cell(row, klasse_idx),
            'klassenstufe': cell(row, klassenstufe_idx),
            'seilbahn': cell(row, seilbahn_idx),
            'kurs': cell(row, kurs_idx),
        })

    return students

# English adjectives (at least one per letter A-Z)
ADJECTIVES = [
    # A
    'active', 'alert', 'awesome', 'agile', 'amazing',
    # B
    'brave', 'bright', 'bold', 'bouncy', 'brilliant',
    # C
    'calm', 'clever', 'cool', 'cheerful', 'creative', 'curious', 'cozy',
    # D
    'daring', 'dazzling', 'delightful', 'dizzy', 'dreamy',
    # E
    'eager', 'enchanting', 'energetic', 'excited',
    # F
    'free', 'fine', 'friendly', 'funny', 'fuzzy', 'fearless', 'fantastic',
    # G
    'gentle', 'great', 'gleeful', 'glowing', 'golden', 'graceful',
    # H
    'happy', 'honest', 'hopeful', 'humble', 'heroic',
    # I
    'inventive', 'incredible', 'imaginative', 'inspired',
    # J
    'jolly', 'joyful', 'jazzy', 'jovial',
    # K
    'kind', 'keen', 'knightly',
    # L
    'lively', 'lucky', 'lovely', 'loyal', 'luminous',
    # M
    'merry', 'magical', 'majestic', 'mindful', 'mighty',
    # N
    'nice', 'noble', 'nimble', 'neat', 'nifty',
    # O
    'optimistic', 'original', 'outstanding', 'open',
    # P
    'proud', 'patient', 'peaceful', 'playful', 'plucky',
    # Q
    'quick', 'quiet', 'quirky',
    # R
    'radiant', 'relaxed', 'reliable', 'remarkable', 'royal',
    # S
    'strong', 'swift', 'smart', 'soft', 'sweet', 'sporty', 'sunny', 'splendid',
    # T
    'talented', 'thoughtful', 'trusty', 'terrific', 'tranquil',
    # U
    'unique', 'upbeat', 'unstoppable',
    # V
    'valiant', 'vibrant', 'vivid', 'versatile',
    # W
    'wild', 'warm', 'wonderful', 'witty', 'wise', 'whimsical',
    # X
    'xenial',
    # Y
    'young', 'youthful', 'yearning',
    # Z
    'zany', 'zealous', 'zen', 'zippy', 'zesty'
]

# English animal names (at least one per letter A-Z)
ANIMALS = [
    # A
    'antelope', 'alpaca', 'armadillo', 'alligator',
    # B
    'bear', 'bird', 'beaver', 'badger', 'bunny', 'butterfly', 'buffalo',
    # C
    'cat', 'cheetah', 'chipmunk', 'crab', 'crane', 'cricket',
    # D
    'dog', 'deer', 'dolphin', 'dove', 'duck', 'dragonfly',
    # E
    'eagle', 'elephant', 'elk', 'emu',
    # F
    'fox', 'fish', 'frog', 'falcon', 'flamingo', 'firefly', 'finch',
    # G
    'goose', 'giraffe', 'gorilla', 'gazelle', 'gecko',
    # H
    'hedgehog', 'horse', 'hamster', 'heron', 'hummingbird', 'hippo', 'hawk',
    # I
    'ibis', 'iguana', 'impala',
    # J
    'jaguar', 'jellyfish', 'jay',
    # K
    'koala', 'kangaroo', 'kiwi', 'kingfisher',
    # L
    'lion', 'leopard', 'lemur', 'llama', 'lobster', 'lark',
    # M
    'mouse', 'moose', 'meerkat', 'macaw', 'mantis', 'mongoose',
    # N
    'narwhal', 'newt', 'nightingale', 'numbat',
    # O
    'owl', 'otter', 'ostrich', 'octopus', 'ocelot', 'oriole',
    # P
    'panda', 'penguin', 'parrot', 'peacock', 'pelican', 'puma', 'porcupine',
    # Q
    'quail', 'quokka',
    # R
    'rabbit', 'raven', 'raccoon', 'reindeer', 'robin', 'ringtail',
    # S
    'swan', 'seal', 'sparrow', 'stork', 'salmon', 'squirrel', 'starfish', 'sloth',
    # T
    'tiger', 'turtle', 'toucan', 'tapir', 'terrapin',
    # U
    'urchin', 'urial',
    # V
    'vicuna', 'vole',
    # W
    'wolf', 'whale', 'wombat', 'woodpecker', 'wren', 'warbler',
    # X
    'xerus',
    # Y
    'yak',
    # Z
    'zebra', 'zorro'
]

CONSONANTS = 'bcdfghjklmnprstvw'
VOWELS = 'aeiou'


# Index adjectives and animals by first letter for matching initials
ADJECTIVES_BY_LETTER = {}
for adj in ADJECTIVES:
    letter = adj[0].lower()
    if letter not in ADJECTIVES_BY_LETTER:
        ADJECTIVES_BY_LETTER[letter] = []
    ADJECTIVES_BY_LETTER[letter].append(adj)

ANIMALS_BY_LETTER = {}
for animal in ANIMALS:
    letter = animal[0].lower()
    if letter not in ANIMALS_BY_LETTER:
        ANIMALS_BY_LETTER[letter] = []
    ANIMALS_BY_LETTER[letter].append(animal)


def generate_username(existing_usernames=None, vorname=None, nachname=None):
    """Generate a unique username like 'happypanda'.

    If vorname (first name) and nachname (last name) are provided,
    tries to match initials (e.g., 'Max Müller' -> 'merrymoose').
    """
    if existing_usernames is None:
        existing_usernames = set()

    # Try to match initials if name is provided
    if vorname and nachname:
        vorname_initial = vorname[0].lower()
        nachname_initial = nachname[0].lower()

        # Get adjectives and animals matching the initials
        matching_adjs = ADJECTIVES_BY_LETTER.get(vorname_initial, [])
        matching_animals = ANIMALS_BY_LETTER.get(nachname_initial, [])

        # If we have matches for both, try those first
        if matching_adjs and matching_animals:
            shuffled_adjs = matching_adjs.copy()
            shuffled_animals = matching_animals.copy()
            random.shuffle(shuffled_adjs)
            random.shuffle(shuffled_animals)

            for adj in shuffled_adjs:
                for animal in shuffled_animals:
                    username = f"{adj}{animal}"
                    if username not in existing_usernames:
                        return username

    # Fallback: random selection
    attempts = 0
    while attempts < 1000:
        adj = random.choice(ADJECTIVES)
        animal = random.choice(ANIMALS)
        username = f"{adj}{animal}"
        if username not in existing_usernames:
            return username
        attempts += 1

    # Last resort: add number
    return f"{adj}{animal}{random.randint(1, 999)}"


def generate_password():
    """Generate password in cvcvcvnn format (e.g., 'bacado42')."""
    password = ''
    password += secrets.choice(CONSONANTS)
    password += secrets.choice(VOWELS)
    password += secrets.choice(CONSONANTS)
    password += secrets.choice(VOWELS)
    password += secrets.choice(CONSONANTS)
    password += secrets.choice(VOWELS)
    password += str(secrets.randbelow(10))
    password += str(secrets.randbelow(10))
    return password


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'pdf', 'png', 'jpg', 'jpeg', 'gif'}


def generate_credentials_pdf(students, klasse_name):
    """Generate a PDF with student credentials.

    Args:
        students: List of dicts with 'nachname', 'vorname', 'username', 'password'
        klasse_name: Name of the class

    Returns:
        BytesIO object containing the PDF
    """
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from datetime import datetime

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    styles = getSampleStyleSheet()

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12
    )
    elements.append(Paragraph(f"Zugangsdaten: {klasse_name}", title_style))
    elements.append(Paragraph(f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 0.5*cm))

    # Warning
    warning_style = ParagraphStyle(
        'Warning',
        parent=styles['Normal'],
        textColor=colors.red,
        fontSize=10
    )
    elements.append(Paragraph(
        "VERTRAULICH - Diese Zugangsdaten sicher aufbewahren und nach Verteilung vernichten!",
        warning_style
    ))
    elements.append(Spacer(1, 0.5*cm))

    # Table header
    data = [['Name', 'Benutzername', 'Passwort']]

    # Table rows
    for s in students:
        data.append([
            f"{s['nachname']}, {s['vorname']}",
            s['username'],
            s['password']
        ])

    # Create table
    table = Table(data, colWidths=[8*cm, 5*cm, 4*cm])
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ALIGN', (1, 1), (-1, -1), 'LEFT'),
        ('FONTNAME', (1, 1), (2, -1), 'Courier'),  # Monospace for credentials
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        # Alternating row colors
        *[('BACKGROUND', (0, i), (-1, i), colors.Color(0.95, 0.95, 0.95))
          for i in range(2, len(data), 2)]
    ]))

    elements.append(table)
    elements.append(Spacer(1, 1*cm))

    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey
    )
    elements.append(Paragraph(
        f"Anzahl Schueler: {len(students)} | Lernmanager",
        footer_style
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_class_report_pdf(report_data, date_from=None, date_to=None):
    """Generate a PDF class progress report.

    Args:
        report_data: Dict with 'klasse' and 'students' from get_report_data_for_class()
        date_from: Optional start date for report period
        date_to: Optional end date for report period

    Returns:
        BytesIO object containing the PDF
    """
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from datetime import datetime

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    styles = getSampleStyleSheet()

    klasse = report_data['klasse']
    students = report_data['students']

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12
    )
    elements.append(Paragraph(
        f"Klassenbericht: {klasse['name']}",
        title_style
    ))

    # Date info
    date_range = ""
    if date_from and date_to:
        date_range = f"Zeitraum: {date_from} bis {date_to}"
    elif date_from:
        date_range = f"Ab {date_from}"
    elif date_to:
        date_range = f"Bis {date_to}"

    if date_range:
        elements.append(Paragraph(date_range, styles['Normal']))
    elements.append(Paragraph(f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 0.5*cm))

    # Statistics
    if students:
        total = len(students)
        active_last_week = sum(1 for s in students if s['login_days'] > 0)
        avg_progress = sum(s['progress_percent'] for s in students) / total if total > 0 else 0
        completed = sum(1 for s in students if s['is_completed'])

        stats_style = ParagraphStyle(
            'Stats',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=6
        )
        elements.append(Paragraph(f"<b>Klassenuebersicht:</b> {total} Schueler", stats_style))
        elements.append(Paragraph(f"Aktive Schueler (im Berichtszeitraum): {active_last_week}", stats_style))
        elements.append(Paragraph(f"Durchschnittlicher Fortschritt: {avg_progress:.0f}%", stats_style))
        elements.append(Paragraph(f"Themen abgeschlossen: {completed}", stats_style))
        elements.append(Spacer(1, 0.5*cm))

    # Table header
    data = [['Name', 'Thema', 'Fortschritt', 'Quiz', 'Login-Tage', 'Letzte Aktivitaet']]

    # Table rows
    for s in students:
        # Progress display
        if s['is_completed']:
            progress = '✓ Fertig'
        elif s['total_subtasks'] > 0:
            progress = f"{s['completed_subtasks']}/{s['total_subtasks']}"
        else:
            progress = '-'

        # Quiz status
        if s['quiz_passed']:
            quiz_status = '✓'
        elif s['total_subtasks'] > 0 and s['completed_subtasks'] == s['total_subtasks']:
            quiz_status = '○'  # Subtasks done but no quiz yet
        else:
            quiz_status = '-'

        # Last activity
        last_activity = '-'
        if s['last_activity']:
            try:
                dt = datetime.fromisoformat(s['last_activity'])
                last_activity = dt.strftime('%d.%m.%Y')
            except:
                last_activity = '-'

        data.append([
            s['name'],
            s['task_name'],
            progress,
            quiz_status,
            str(s['login_days']),
            last_activity
        ])

    # Create table
    table = Table(data, colWidths=[5*cm, 4*cm, 2.5*cm, 1.5*cm, 2*cm, 2.5*cm])
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (2, 1), (-1, -1), 'CENTER'),  # Center progress, quiz, login days, last activity
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        # Alternating row colors
        *[('BACKGROUND', (0, i), (-1, i), colors.Color(0.95, 0.95, 0.95))
          for i in range(2, len(data), 2)]
    ]))

    elements.append(table)
    elements.append(Spacer(1, 1*cm))

    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey
    )
    elements.append(Paragraph(
        f"Lernmanager - Klassenbericht | Schueleranzahl: {len(students)}",
        footer_style
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_student_report_pdf(report_data, report_type='summary'):
    """Generate a PDF student progress report (admin version).

    Args:
        report_data: Dict from get_report_data_for_student()
        report_type: 'summary' or 'complete'

    Returns:
        BytesIO object containing the PDF
    """
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from datetime import datetime

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    styles = getSampleStyleSheet()

    student = report_data['student']
    summary = report_data['summary']
    current_tasks = report_data['current_tasks']

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12
    )
    elements.append(Paragraph(
        f"Fortschrittsbericht: {student['nachname']}, {student['vorname']}",
        title_style
    ))
    elements.append(Paragraph(
        f"Benutzername: {student['username']} | Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        styles['Normal']
    ))
    elements.append(Spacer(1, 0.5*cm))

    # Summary section
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=10,
        textColor=colors.HexColor('#2563eb')
    )
    elements.append(Paragraph("Uebersicht", section_style))

    # Summary data (tasks_completed is a list, get count)
    tasks_count = len(summary['tasks_completed']) if isinstance(summary['tasks_completed'], list) else summary['tasks_completed']
    summary_data = [
        ['Aktive Lerntage', str(summary['login_days'])],
        ['Themen abgeschlossen', str(tasks_count)],
        ['Quiz bestanden', str(summary['event_counts'].get('quiz_attempt', 0))],
        ['Dateien heruntergeladen', str(summary['event_counts'].get('file_download', 0))]
    ]

    summary_table = Table(summary_data, colWidths=[8*cm, 4*cm])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, -1), colors.Color(0.97, 0.97, 0.97))
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.5*cm))

    # Current tasks section
    if current_tasks:
        elements.append(Paragraph("Aktuelle Themen", section_style))

        task_data = [['Klasse', 'Thema', 'Fortschritt', 'Quiz', 'Status']]
        for task in current_tasks:
            progress = f"{task['completed_subtasks']}/{task['total_subtasks']}"
            quiz = '✓' if task['quiz_passed'] else '○'
            status = 'Abgeschlossen' if task['is_completed'] else 'In Bearbeitung'

            task_data.append([
                task['klasse_name'],
                task['name'],
                progress,
                quiz,
                status
            ])

        task_table = Table(task_data, colWidths=[3.5*cm, 4*cm, 2.5*cm, 1.5*cm, 3*cm])
        task_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (2, 1), (3, -1), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            *[('BACKGROUND', (0, i), (-1, i), colors.Color(0.95, 0.95, 0.95))
              for i in range(2, len(task_data), 2)]
        ]))
        elements.append(task_table)
        elements.append(Spacer(1, 0.5*cm))

    # Complete report additional sections
    if report_type == 'complete' and 'activity_log' in report_data:
        elements.append(PageBreak())
        elements.append(Paragraph("Aktivitaetsprotokoll", section_style))

        # activity_log is a list directly, not a dict with 'events' key
        activity_log = report_data.get('activity_log', [])
        if activity_log:
            activity_data = [['Datum', 'Aktivitaet', 'Details']]
            for event in activity_log[:50]:  # Limit to 50 events for PDF
                try:
                    timestamp = datetime.fromisoformat(event['timestamp']).strftime('%d.%m %H:%M')
                except:
                    timestamp = '-'

                event_type_names = {
                    'login': 'Login',
                    'page_view': 'Seitenaufruf',
                    'file_download': 'Download',
                    'subtask_complete': 'Aufgabe',
                    'task_complete': 'Thema fertig',
                    'quiz_attempt': 'Quiz',
                    'self_eval': 'Selbsteinschaetzung'
                }
                event_name = event_type_names.get(event['event_type'], event['event_type'])

                details = '-'
                if event.get('metadata'):
                    import json
                    try:
                        meta = json.loads(event['metadata'])
                        if event['event_type'] == 'quiz_attempt':
                            details = f"{meta.get('score', '-')}/{meta.get('total_questions', '-')} ({'✓' if meta.get('passed') else '✗'})"
                        elif event['event_type'] == 'file_download':
                            details = meta.get('filename', '-')
                    except:
                        pass

                activity_data.append([timestamp, event_name, details])

            activity_table = Table(activity_data, colWidths=[3*cm, 4*cm, 8*cm])
            activity_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                *[('BACKGROUND', (0, i), (-1, i), colors.Color(0.95, 0.95, 0.95))
                  for i in range(2, len(activity_data), 2)]
            ]))
            elements.append(activity_table)

    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey
    )
    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph(
        f"Lernmanager - Fortschrittsbericht ({'Vollstaendig' if report_type == 'complete' else 'Zusammenfassung'})",
        footer_style
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_student_self_report_pdf(report_data):
    """Generate a PDF student self-report (student-facing version with positive framing).

    Args:
        report_data: Dict from get_report_data_for_student()

    Returns:
        BytesIO object containing the PDF
    """
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from datetime import datetime

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    styles = getSampleStyleSheet()

    student = report_data['student']
    summary = report_data['summary']
    current_tasks = report_data['current_tasks']

    # Title with positive framing
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        spaceAfter=16,
        textColor=colors.HexColor('#2563eb')
    )
    elements.append(Paragraph(
        f"Dein Lernfortschritt",
        title_style
    ))
    elements.append(Paragraph(
        f"{student['vorname']} {student['nachname']} | {datetime.now().strftime('%d.%m.%Y')}",
        styles['Normal']
    ))
    elements.append(Spacer(1, 0.7*cm))

    # Progress-focused introduction
    intro_style = ParagraphStyle(
        'Intro',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=12,
        textColor=colors.HexColor('#1e40af')
    )

    # Build encouraging message based on data
    login_days = summary['login_days']
    # tasks_completed is a list of task dicts, get count
    tasks_completed_count = len(summary['tasks_completed']) if isinstance(summary['tasks_completed'], list) else summary['tasks_completed']
    quiz_passes = summary['event_counts'].get('quiz_attempt', 0)

    encouragement = ""
    if login_days > 10:
        encouragement = f"Du warst {login_days} Tage aktiv - super Einsatz! "
    elif login_days > 0:
        encouragement = f"Du warst {login_days} Tage aktiv. "

    if tasks_completed_count > 0:
        encouragement += f"Du hast bereits {tasks_completed_count} Thema{'en' if tasks_completed_count > 1 else ''} abgeschlossen. "

    if not encouragement:
        encouragement = "Deine Lernreise hat begonnen. "

    encouragement += "Weiter so!"

    elements.append(Paragraph(encouragement, intro_style))
    elements.append(Spacer(1, 0.5*cm))

    # Simple key metrics
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=10,
        textColor=colors.HexColor('#2563eb')
    )
    elements.append(Paragraph("Deine Fortschritte", section_style))

    # Metrics with positive language
    metrics_data = []
    if login_days > 0:
        metrics_data.append(['Aktive Lerntage', Paragraph(f"<b>{login_days}</b>", styles['Normal'])])
    if tasks_completed_count > 0:
        metrics_data.append(['Themen abgeschlossen', Paragraph(f"<b>{tasks_completed_count}</b>", styles['Normal'])])
    if quiz_passes > 0:
        metrics_data.append(['Quiz bestanden', Paragraph(f"<b>{quiz_passes}</b>", styles['Normal'])])

    if not metrics_data:
        metrics_data.append(['Status', Paragraph('<b>Bereit zum Loslegen!</b>', styles['Normal'])])

    metrics_table = Table(metrics_data, colWidths=[9*cm, 5*cm])
    metrics_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#2563eb')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eff6ff'))
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 0.7*cm))

    # Current task progress
    if current_tasks:
        elements.append(Paragraph("Deine aktuellen Themen", section_style))

        task_data = []
        for task in current_tasks:
            completed = task['completed_subtasks']
            total = task['total_subtasks']

            # Progress description with positive framing
            if task['is_completed']:
                progress_text = "✓ Fertig!"
            elif completed == total and not task['quiz_passed']:
                progress_text = f"{completed}/{total} - Noch Quiz"
            elif completed > 0:
                progress_text = f"{completed} von {total} Aufgaben"
            else:
                progress_text = "Bereit zum Start"

            task_data.append([
                Paragraph(task['klasse_name'], styles['Normal']),
                Paragraph(task['name'], styles['Normal']),
                Paragraph(progress_text, styles['Normal'])
            ])

        task_table = Table(task_data, colWidths=[4*cm, 6*cm, 4*cm])
        task_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (-1, -1), colors.Color(0.97, 0.97, 0.97)),
            ('ALIGN', (2, 0), (2, -1), 'CENTER')
        ]))
        elements.append(task_table)
        elements.append(Spacer(1, 0.7*cm))

    # Motivational footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#2563eb'),
        alignment=1  # Center
    )
    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph(
        "<i>Jeder Schritt bringt dich weiter. Bleib dran!</i>",
        footer_style
    ))

    # Bottom attribution
    attr_style = ParagraphStyle(
        'Attribution',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey,
        alignment=1  # Center
    )
    elements.append(Spacer(1, 0.3*cm))
    elements.append(Paragraph("Lernmanager - Dein Fortschrittsbericht", attr_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
