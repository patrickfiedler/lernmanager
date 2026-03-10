# Lernmanager

A German-language learning progress tracker for schools. Teachers manage classes, students, and learning topics; students track their progress and take quizzes.

## Features

### For Teachers

- Create and manage classes with weekly schedules
- Batch-import students ("Nachname, Vorname" per line) — credentials auto-generated
- Create topics (Themen) with tasks (Aufgaben), materials, and quizzes
- Three question types: multiple choice, fill-in-the-blank, short answer (LLM-graded)
- Assign topics to individual students or entire classes
- Define learning paths per student: 🟢 Wanderweg · 🔵 Bergweg · ⭐ Gipfeltour · 🚡 Seilbahn
- Set a topic queue per class for self-paced progression
- Track lesson attendance and per-student evaluations
- PDF progress reports for class and individual students
- Optional AI-based completeness check for student artifacts (per-class toggle)
- DSGVO-compliant: no IP logging, data export and deletion per Art. 15/17

### For Students

- Step-by-step task completion with progress indicators
- Per-task and topic-level quizzes (70% pass threshold)
- Login warm-up: 2–4 spaced-repetition questions on previously learned material
- Practice mode: random, weakness-focused, or topic-filtered question sets
- Optional AI completeness check for uploaded artifacts (preview before sending)
- Datenschutzerklärung accessible without login

## Technology

- **Backend**: Python 3, Flask
- **Database**: SQLite
- **Server**: Waitress WSGI
- **Frontend**: Custom CSS, vanilla JavaScript
- **LLM grading**: OpenAI-compatible API endpoint (e.g. OVHcloud AI Endpoints with open-source models)
- **PDF**: ReportLab

## Installation

### Local Development

```bash
git clone https://github.com/patrickfiedler/lernmanager.git
cd lernmanager
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

App runs at `http://localhost:5000`.

### Production

**One-command setup:**
```bash
curl -sSL https://raw.githubusercontent.com/patrickfiedler/lernmanager/main/deploy/setup.sh | sudo bash
```

**Updates:**
```bash
ssh user@server 'sudo /opt/lernmanager/deploy/update.sh'
```

## Configuration

Key environment variables (set in systemd service or `.env`):

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask session secret (auto-generated on first deploy) |
| `LLM_PROVIDER` | LLM provider name (default: `ovhcloud`) |
| `LLM_API_KEY` | API key for the LLM provider |
| `LLM_BASE_URL` | Provider endpoint URL (required for `ovhcloud`) |
| `LLM_MODEL` | Model name |

## License

AGPL-3.0

## Author

Patrick Fiedler · [@patrickfiedler](https://github.com/patrickfiedler)
