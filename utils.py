import random

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
    'jaguar', 'jellyfish', 'jackrabbit', 'jay',
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
    'rabbit', 'raven', 'raccoon', 'reindeer', 'robin', 'rooster',
    # S
    'swan', 'seal', 'sparrow', 'stork', 'salmon', 'squirrel', 'starfish', 'sloth',
    # T
    'tiger', 'turtle', 'toucan', 'tapir', 'termite',
    # U
    'urchin', 'urial',
    # V
    'viper', 'vulture', 'vicuna',
    # W
    'wolf', 'whale', 'walrus', 'wombat', 'woodpecker', 'wren',
    # X
    'xerus',
    # Y
    'yak', 'yellowjacket',
    # Z
    'zebra', 'zebrafish'
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
    password += random.choice(CONSONANTS)
    password += random.choice(VOWELS)
    password += random.choice(CONSONANTS)
    password += random.choice(VOWELS)
    password += random.choice(CONSONANTS)
    password += random.choice(VOWELS)
    password += str(random.randint(0, 9))
    password += str(random.randint(0, 9))
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
        elements.append(Paragraph(f"Aufgaben abgeschlossen: {completed}", stats_style))
        elements.append(Spacer(1, 0.5*cm))

    # Table header
    data = [['Name', 'Aufgabe', 'Fortschritt', 'Quiz', 'Login-Tage', 'Letzte Aktivitaet']]

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
        ['Aufgaben abgeschlossen', str(tasks_count)],
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
        elements.append(Paragraph("Aktuelle Aufgaben", section_style))

        task_data = [['Klasse', 'Aufgabe', 'Fortschritt', 'Quiz', 'Status']]
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
                    'subtask_complete': 'Teilaufgabe',
                    'task_complete': 'Aufgabe fertig',
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
        encouragement += f"Du hast bereits {tasks_completed_count} Aufgabe{'n' if tasks_completed_count > 1 else ''} abgeschlossen. "

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
        metrics_data.append(['Aktive Lerntage', f"<b>{login_days}</b>"])
    if tasks_completed_count > 0:
        metrics_data.append(['Aufgaben abgeschlossen', f"<b>{tasks_completed_count}</b>"])
    if quiz_passes > 0:
        metrics_data.append(['Quiz bestanden', f"<b>{quiz_passes}</b>"])

    if not metrics_data:
        metrics_data.append(['Status', '<b>Bereit zum Loslegen!</b>'])

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
        elements.append(Paragraph("Deine aktuellen Aufgaben", section_style))

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
                progress_text = f"{completed} von {total} Teilaufgaben"
            else:
                progress_text = "Bereit zum Start"

            task_data.append([
                task['klasse_name'],
                task['name'],
                progress_text
            ])

        task_table = Table(task_data, colWidths=[4*cm, 5*cm, 5*cm])
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
