"""Record WHICH per-question scores a teacher set by hand.

question_scores_json already holds the effective 0/2/3 breakdown behind a session's
score, but says nothing about where a value came from. Without that, a hand-set 2
renders identically to a computed 2 in the review page -- the teacher cannot see
their own correction, and neither can the export Chemie reads.

Shape: JSON object keyed by the question's index in the stored quiz, as a string,
exactly like question_scores_json. Value 0/2/3, or null for "does not count".
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def main():
    conn = sqlite3.connect(config.DATABASE)
    try:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(checkpoint_attempt)')}
        if 'question_scores_manual_json' in columns:
            print('question_scores_manual_json already present, nothing to do')
            return
        conn.execute('ALTER TABLE checkpoint_attempt ADD COLUMN question_scores_manual_json TEXT')
        conn.commit()
        print('checkpoint_attempt.question_scores_manual_json added')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
