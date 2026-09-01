import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# SECRET_KEY is required in production
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if os.environ.get('FLASK_ENV') == 'production':
        print("ERROR: SECRET_KEY environment variable is required in production!", file=sys.stderr)
        print("Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\"", file=sys.stderr)
        sys.exit(1)
    else:
        # Development fallback - insecure but convenient
        SECRET_KEY = 'dev-secret-key-not-for-production'
        print("WARNING: Using insecure development SECRET_KEY. Set SECRET_KEY env var for production.", file=sys.stderr)
# School identity (shown in Datenschutzerklärung)
SCHOOL_NAME = os.environ.get('SCHOOL_NAME', '[Schulname]')
SCHOOL_ADDRESS = os.environ.get('SCHOOL_ADDRESS', '[Adresse]')
SCHOOL_EMAIL = os.environ.get('SCHOOL_EMAIL', '[E-Mail-Adresse]')
DSB_CONTACT = os.environ.get('DSB_CONTACT', '')
PRIVACY_AUTHORITY = os.environ.get('PRIVACY_AUTHORITY', '[Landesbeauftragter für Datenschutz]')

DATABASE = os.path.join(BASE_DIR, 'data', 'mbi_tracker.db')
# Store uploads outside static/ to require authentication for access
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'instance', 'uploads')
MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 MB max upload

# Allowed file extensions for material uploads.
#
# Split in two because the split decides how the file is *served*, not just
# whether it is accepted (see app.download_material): a PDF or an image is
# shown in the browser, everything else is handed over as a download. Serving
# an unknown type inline on our own origin is what turns a stray .html in a
# content bundle into a script running as the logged-in user.
#
# The document formats are not optional extras: artifact_gate.min_added_words
# resolves template_material against a real material file on disk (e.g.
# "01_Startklar_Vorlage.docx"), so docx/pptx must be storable as materials.
# They arrived through the ZIP import, which used to check nothing at all.
INLINE_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}
DOWNLOAD_EXTENSIONS = {'docx', 'pptx', 'odt', 'odp', 'sb3', 'zip'}
ALLOWED_EXTENSIONS = INLINE_EXTENSIONS | DOWNLOAD_EXTENSIONS

# Subject and level options
SUBJECTS = ['Englisch', 'Chemie', 'MBI', 'Geographie']
# Grade levels: single integers (5, 6, 7, ...) since 2026-08-25. The old
# double-year values ('5/6', '7/8', '9/10') collided as soon as two units
# shared a name across grades -- see docs/shared/lernmanager/task_json_format.md.
# LEGACY_LEVELS are still rendered for existing rows but no longer offered.
# 'Seilbahn' is deliberately absent: it is a *path* (subtask.path / student.lernpfad,
# see models.VALID_PATHS), not a grade level. It sat here only as a label hack to tell
# a Seilbahn variant from its regular twin in the admin dropdown -- derive that from
# the subtask paths instead (import_task._is_seilbahn_topic).
LEVELS = ['5', '6', '7', '8', '9', '10', '11s', '11/12']
LEGACY_LEVELS = ['5/6', '7/8', '9/10']

# Zeichenleiste: character-insert bars offered above free-text answer fields.
# Keyed by Fach (task.fach, same spelling as SUBJECTS above). A student sees the
# bar for every subject their classes actually work on; a subject that is not a
# key here -- which is all of them but Chemie -- gets no bar and no change.
#
# Not a per-class setting: klasse has no `fach` column, the subject lives on the
# Thema, and one real class ("Klasse x") runs Chemie and MBI side by side. A
# declared class subject would be plainly wrong for that one, and would need
# setting on eleven others before anything happened.
#
# Why the set exists: asked for by Chemie 2026-08-29
# (docs/shared/lernmanager/inbox.md). Of thirty answers to the two half-equation
# questions in the 2026-08-26 run, not one contained a reaction arrow, a subscript
# digit or a superscript charge. Students on iPads reach for "->" or "wird zu"
# because the keyboard offers nothing else, and the notation is itself exam
# content they have to write by hand later.
# A plain string is a key that shows and inserts the same character. A dict
# splits the two: `anchor` is a dimmed "x" drawn beside the character, so a key
# reads as x2-superscript rather than a lone superscript glyph -- on an iPad the
# raised and the lowered digit differ only by height inside an empty key, which
# is no difference at all. Only `char` is ever inserted; `name` is what a screen
# reader says, since "Zeichen 2" would not say which of the two it is.
#
# Charges are built from parts (3 then +) rather than offered pre-composed:
# students need 4+ and 2- as much as 2+, and one key per part covers all of them.
# There is no key for a raised or lowered 1 -- chemistry never writes either.
CHARACTER_SETS = {
    'Chemie': [
        '\u2192',                                                          # ->
        '\u21cc',                                                          # equilibrium
        {'char': '\u00b2', 'anchor': 'x', 'name': 'hochgestellte 2'},
        {'char': '\u00b3', 'anchor': 'x', 'name': 'hochgestellte 3'},
        {'char': '\u2074', 'anchor': 'x', 'name': 'hochgestellte 4'},
        {'char': '\u207a', 'anchor': 'x', 'name': 'hochgestelltes Plus'},
        {'char': '\u207b', 'anchor': 'x', 'name': 'hochgestelltes Minus'},
        {'char': '\u2082', 'anchor': 'x', 'name': 'tiefgestellte 2'},
        {'char': '\u2083', 'anchor': 'x', 'name': 'tiefgestellte 3'},
        {'char': '\u2084', 'anchor': 'x', 'name': 'tiefgestellte 4'},
        '\u0394',                                                          # Delta
        '\u00b0',
    ],
}


def _env_int(name, default, minimum=1):
    """Read a positive int from the environment, falling back to `default`.

    A typo in .env must not take the app down -- students losing access to the
    whole platform is a worse outcome than one mistuned limit -- so a bad value
    warns on stderr and uses the default rather than raising at import time.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"WARNING: {name}={raw!r} is not an integer -- using {default}.", file=sys.stderr)
        return default
    if value < minimum:
        print(f"WARNING: {name}={value} is below {minimum} -- using {default}.", file=sys.stderr)
        return default
    return value


# Local timezone for every timestamp written to the DB.
# SQLite's CURRENT_TIMESTAMP is UTC, always, regardless of the server clock -- which
# is why some rows read two hours early in summer while the VPS itself showed the
# right time. Timestamps are now generated in Python against this zone (see
# models.now_local) so the value does not depend on the server's TZ env var either.
TIMEZONE = os.environ.get('TIMEZONE', 'Europe/Berlin')

# LLM grading (for free-text quiz questions and artifact completeness checks)
# Uses any OpenAI-compatible API endpoint (e.g. OVHcloud AI Endpoints).
# Set LLM_API_KEY to the provider access token.
# Set LLM_BASE_URL to the provider endpoint URL (required).
LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'ovhcloud')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_BASE_URL = os.environ.get('LLM_BASE_URL', None)
LLM_MODEL = os.environ.get('LLM_MODEL', 'Qwen/Qwen3-32B-FP8')
LLM_TIMEOUT = _env_int('LLM_TIMEOUT', 5)  # seconds (quiz grading — short answers)
# Checkpoint answers are longer, multi-sentence explanations graded against the
# stricter CHECKPOINT_SYSTEM_PROMPT, and they feed a real grade -- a timeout there
# costs an attempt rather than a practice retry, so they get more room than the 5s
# formative-quiz budget. Checkpoints are answered one at a time over AJAX behind a
# visible wait state, so a slower ceiling costs one spinner, not a stalled page.
LLM_CHECKPOINT_TIMEOUT = _env_int('LLM_CHECKPOINT_TIMEOUT', 15)
LLM_ARTIFACT_TIMEOUT = _env_int('LLM_ARTIFACT_TIMEOUT', 60)  # seconds (artifact checklist — up to 20 criteria)
# The artifact check must finish inside nginx's proxy_read_timeout, or nginx
# hands the student a raw 504 instead of the app's own "KI-Feedback nicht
# verfügbar" page. nginx is NOT configured from here -- it is edited by hand on
# the server (deploy/lernmanager.nginx.conf is only a template, and certbot
# rewrites that server block) -- so raising this knob alone silently reintroduces
# the timeout. Warn rather than clamp: the ceiling is a deployment fact this
# process cannot read.
NGINX_PROXY_READ_TIMEOUT = _env_int('NGINX_PROXY_READ_TIMEOUT', 90)
if LLM_ARTIFACT_TIMEOUT >= NGINX_PROXY_READ_TIMEOUT:
    print(
        f"WARNING: LLM_ARTIFACT_TIMEOUT={LLM_ARTIFACT_TIMEOUT}s is not below "
        f"nginx proxy_read_timeout ({NGINX_PROXY_READ_TIMEOUT}s). Slow artifact "
        f"checks will fail as 504 Gateway Timeout instead of a readable message. "
        f"Raise proxy_read_timeout/proxy_send_timeout on the server too.",
        file=sys.stderr,
    )
LLM_MAX_CALLS_PER_STUDENT_PER_HOUR = _env_int('LLM_MAX_CALLS_PER_STUDENT_PER_HOUR', 20)          # quiz/warmup answers
LLM_MAX_ARTIFACT_CHECKS_PER_STUDENT_PER_HOUR = _env_int('LLM_MAX_ARTIFACT_CHECKS_PER_STUDENT_PER_HOUR', 10)  # artifact KI-Check uploads
# Chemie Checkpoint-Punktekonto: graded checkpoint quizzes must not run out of
# budget mid-session just because the same student also did warmup/practice
# earlier that hour -- own pool, own (higher) ceiling. A module has up to ~8
# quiz-checkpoints, majority short_answer, plus retries -- 60 gives headroom
# for a full lesson without being effectively unlimited.
LLM_MAX_CHECKPOINT_CALLS_PER_STUDENT_PER_HOUR = _env_int('LLM_MAX_CHECKPOINT_CALLS_PER_STUDENT_PER_HOUR', 60)
LLM_ENABLED = bool(LLM_API_KEY)
# OVHcloud Qwen3-32B fp8 pricing (per 1M tokens, as of 2026-03):
#   input: €0.09 | output: €0.27
# Cost per artifact check: ~€0.0002 (9 criteria) to ~€0.0004 (23 criteria)

# Grading service (grading-with-llm, runs on the M920x over WireGuard).
# GRADING_SERVICE_CALLBACK_SECRET must match that box's _CALLBACK_SECRET env
# var -- checked against the X-Grading-Callback-Secret header on
# /internal/grading/results (grading-service-deployment.md §7/§10 Phase 2).
GRADING_SERVICE_URL = os.environ.get('GRADING_SERVICE_URL', '')
GRADING_SERVICE_TOKEN = os.environ.get('GRADING_SERVICE_TOKEN', '')
GRADING_SERVICE_CALLBACK_SECRET = os.environ.get('GRADING_SERVICE_CALLBACK_SECRET', '')
