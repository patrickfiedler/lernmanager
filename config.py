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
DSB_CONTACT = os.environ.get('DSB_CONTACT', '[Datenschutzbeauftragte/r: Name, Kontakt]')
PRIVACY_AUTHORITY = os.environ.get('PRIVACY_AUTHORITY', '[Landesbeauftragter für Datenschutz]')

DATABASE = os.path.join(BASE_DIR, 'data', 'mbi_tracker.db')
# Store uploads outside static/ to require authentication for access
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'instance', 'uploads')
MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 MB max upload

# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}

# Subject and level options
SUBJECTS = ['Englisch', 'Chemie', 'MBI', 'Geographie']
LEVELS = ['5/6', '7/8', '9/10', '11s', '11/12', 'Seilbahn']

# LLM grading (for free-text quiz questions and artifact completeness checks)
# Uses any OpenAI-compatible API endpoint (e.g. OVHcloud AI Endpoints).
# Set LLM_API_KEY to the provider access token.
# Set LLM_BASE_URL to the provider endpoint URL (required).
LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'ovhcloud')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_BASE_URL = os.environ.get('LLM_BASE_URL', None)
LLM_MODEL = os.environ.get('LLM_MODEL', 'Qwen/Qwen3-32B-FP8')
LLM_TIMEOUT = 5  # seconds (quiz grading — short answers)
LLM_ARTIFACT_TIMEOUT = 60  # seconds (artifact checklist — up to 20 criteria)
LLM_MAX_CALLS_PER_STUDENT_PER_HOUR = 20          # quiz/warmup answers
LLM_MAX_ARTIFACT_CHECKS_PER_STUDENT_PER_HOUR = 10  # artifact KI-Check uploads
LLM_ENABLED = bool(LLM_API_KEY)
# OVHcloud Qwen3-32B fp8 pricing (per 1M tokens, as of 2026-03):
#   input: €0.09 | output: €0.27
# Cost per artifact check: ~€0.0002 (9 criteria) to ~€0.0004 (23 criteria)
