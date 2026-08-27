"""Convert historic UTC timestamps to local wall-clock time.

SQLite's CURRENT_TIMESTAMP is UTC unconditionally, so every column that used it as
a default or wrote it explicitly stored UTC, while the rest of the app wrote local
time via datetime.now(). The DB therefore held two time bases at once, and the UI
-- which renders the stored text verbatim -- showed those rows two hours early in
summer (reported 2026-08-27: "7:16 instead of 9:16", VPS clock correct at CEST).

Going forward every write goes through models.now_local(). This migration fixes the
rows already written.

The shift is NOT a fixed +2h. These rows span the 2026 DST change (29 March), so
winter rows are UTC+1 and summer rows UTC+2. Each value is converted individually
through ZoneInfo, which knows where the boundary falls.

Columns deliberately NOT touched, because they were already local:
  analytics_events.timestamp        -- written by analytics_queue with datetime.now()
  artifact_feedback.timestamp_local -- name says it; written with datetime.now()
  warmup_history.last_shown         -- a local date, compared against a local date
  every grading_* / student_artifact_file column -- all datetime.now()

Idempotent: records a marker in app_settings, so a second run cannot double-shift.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime, timezone as dt_timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE, TIMEZONE

MARKER_KEY = 'tz_backfill_050_done'

# (table, column) pairs that held UTC.
UTC_COLUMNS = [
    ('checkpoint_attempt', 'timestamp'),
    ('checkpoint_attempt', 'superseded_at'),
    ('checkpoint_attempt', 'reviewed_at'),
    ('checkpoint_answer', 'timestamp'),
    ('quiz_attempt', 'timestamp'),
    ('llm_usage', 'timestamp'),
    ('warmup_session', 'timestamp'),
    ('error_log', 'timestamp'),
    ('subtask_visibility', 'set_at'),
    ('app_settings', 'updated_at'),
    ('saved_reports', 'date_generated'),
]

FORMATS = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']


def to_local(value, zone):
    """'2026-08-26 07:16:00' (UTC) -> '2026-08-26 09:16:00' (Europe/Berlin).

    Returns None when the value is not a timestamp this migration understands --
    the caller then leaves the row alone rather than guessing.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in FORMATS:
        try:
            naive = datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        aware_utc = naive.replace(tzinfo=dt_timezone.utc)
        return aware_utc.astimezone(zone).strftime('%Y-%m-%d %H:%M:%S')
    return None


def run():
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(TIMEZONE)
    except Exception as exc:
        sys.exit(f"Cannot load timezone {TIMEZONE!r}: {exc}. Install tzdata and retry.")

    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        if 'app_settings' in tables:
            done = conn.execute("SELECT value FROM app_settings WHERE key = ?",
                                (MARKER_KEY,)).fetchone()
            if done:
                print(f"Already applied on {done['value']} -- skipping "
                      f"(re-running would shift every timestamp a second time).")
                return

        total = skipped = 0
        for table, column in UTC_COLUMNS:
            if table not in tables:
                continue
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                continue
            rows = conn.execute(
                f"SELECT rowid AS _rid, {column} AS _val FROM {table} "
                f"WHERE {column} IS NOT NULL").fetchall()
            changed = 0
            for r in rows:
                new = to_local(r['_val'], zone)
                if new is None:
                    skipped += 1
                    continue
                if new != r['_val']:
                    conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                                 (new, r['_rid']))
                    changed += 1
            if changed:
                print(f"  {table}.{column}: {changed} row(s) converted")
            total += changed

        # Rows this app wrote when its pytz import failed were labelled 'UTC'
        # explicitly -- the one place the old code admitted it had fallen back.
        if 'artifact_gate_attempt' in tables:
            rows = conn.execute(
                "SELECT rowid AS _rid, timestamp_local AS _val FROM artifact_gate_attempt "
                "WHERE timezone = 'UTC'").fetchall()
            for r in rows:
                new = to_local(r['_val'], zone)
                if new:
                    conn.execute(
                        "UPDATE artifact_gate_attempt SET timestamp_local = ?, timezone = ? "
                        "WHERE rowid = ?", (new, TIMEZONE, r['_rid']))
                    total += 1
            if rows:
                print(f"  artifact_gate_attempt: {len(rows)} UTC-labelled row(s) converted")

        if 'app_settings' in tables:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (MARKER_KEY, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        conn.commit()
        print(f"\nDone. {total} timestamp(s) converted to {TIMEZONE}"
              f"{f', {skipped} unrecognised value(s) left alone' if skipped else ''}.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
