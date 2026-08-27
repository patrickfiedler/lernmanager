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

# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}

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
