"""Warm-up answer log + LLM call metadata (chemie request 2026-11-18, Patrick).

    warmup_answer   one row per answered warm-up/practice question. warmup_history
                    keeps only running totals, so "how well does a question sit after
                    1/3/7/14 days" was not answerable. days_since_last + streak_before
                    are the history row's state *before* this answer -- the history row
                    itself is overwritten. phase separates warm-up from practice, which
                    both update the same warmup_history.

    llm_usage       + model, prompt_version, latency_ms, input_tokens, output_tokens,
                    ok, error. Failed calls are now recorded too (ok = 0); the rate
                    limits count only ok = 1, so a provider outage does not eat a
                    student's hourly budget. Old rows get ok = 1 (they were successes).
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

# Written out, not generated: tests/test_schema_parity.py finds columns by
# scanning for literal "ALTER TABLE x ADD COLUMN y".
LLM_COLUMNS = {
    "model": "ALTER TABLE llm_usage ADD COLUMN model TEXT",
    "prompt_version": "ALTER TABLE llm_usage ADD COLUMN prompt_version TEXT",
    "latency_ms": "ALTER TABLE llm_usage ADD COLUMN latency_ms INTEGER",
    "input_tokens": "ALTER TABLE llm_usage ADD COLUMN input_tokens INTEGER",
    "output_tokens": "ALTER TABLE llm_usage ADD COLUMN output_tokens INTEGER",
    "ok": "ALTER TABLE llm_usage ADD COLUMN ok INTEGER NOT NULL DEFAULT 1",
    "error": "ALTER TABLE llm_usage ADD COLUMN error TEXT",
}


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS warmup_answer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT (datetime('now','localtime')),
                phase TEXT NOT NULL,
                task_id INTEGER,
                subtask_id INTEGER,
                question_hash TEXT NOT NULL,
                question_type TEXT,
                correct INTEGER NOT NULL,
                grader TEXT,
                days_since_last INTEGER,
                streak_before INTEGER,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warmup_answer_student_time "
                     "ON warmup_answer(student_id, timestamp)")
        print("  warmup_answer table ready.")

        cols = {row[1] for row in conn.execute("PRAGMA table_info(llm_usage)").fetchall()}
        for name, statement in LLM_COLUMNS.items():
            if name in cols:
                print(f"  llm_usage.{name} already exists, skipping.")
            else:
                conn.execute(statement)
                print(f"  Added llm_usage.{name}.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
