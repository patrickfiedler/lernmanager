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
DATABASE = os.path.join(BASE_DIR, 'data', 'mbi_tracker.db')
# Store uploads outside static/ to require authentication for access
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'instance', 'uploads')
MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 MB max upload

# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}

# Subject and level options
SUBJECTS = ['Englisch', 'Chemie', 'MBI', 'Geographie']
LEVELS = ['5/6', '7/8', '9/10', '11s', '11/12']

# LLM grading (for free-text quiz questions)
# LLM_PROVIDER: 'anthropic' (default) or 'ovhcloud'
#   anthropic: uses Anthropic SDK. LLM_BASE_URL can point to Ollama (Anthropic-compat mode).
#   ovhcloud:  uses OpenAI-compatible SDK. Set LLM_API_KEY to OVH_AI_ENDPOINTS_ACCESS_TOKEN.
#              LLM_BASE_URL defaults to OVHcloud's kepler endpoint.
LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'anthropic')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_BASE_URL = os.environ.get('LLM_BASE_URL', None)
LLM_MODEL = os.environ.get('LLM_MODEL', 'claude-haiku-4-5-20251001')
LLM_TIMEOUT = 5  # seconds
LLM_MAX_CALLS_PER_STUDENT_PER_HOUR = 20
LLM_ENABLED = bool(LLM_API_KEY)
