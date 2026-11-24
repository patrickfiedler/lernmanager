"""Checkpoint questions get a fixed id; stored data is tied to it, not to a position.

Why (Patrick + chemie, 2026-11-24): scores, answers, flags, exclusions and notes are
keyed by a question's POSITION. Deleting a question from the start or middle of a
checkpoint shifts every later score onto the wrong question -- it already happened
once in 1.3. Design and decisions: task_plan.md § Feste Frage-IDs; every old wording
without an exact match was decided by hand:
docs/shared/lernmanager/2026-11-24-frage-ids-zuordnung.md

ADDITIVE, with one exception. Nothing that exists is changed or removed, so old
code can still read every row:
  - each checkpoint question in subtask.quiz_json gets "id" (f1, f2, ... by today's
    position; an id already present is kept)
  - snapshots (checkpoint_attempt.quiz_snapshot_json, checkpoint_answer.
    question_snapshot_json) get the id of the question they were
  - new columns: checkpoint_attempt.question_scores_by_id_json /
    question_scores_manual_by_id_json, and question_id on checkpoint_answer,
    checkpoint_flag, checkpoint_question_exclusion, checkpoint_question_note
The exception: checkpoint_question_exclusion and checkpoint_question_note are
rebuilt with their primary key on question_id instead of question_index. Keyed on
the position, excluding question 2 after question 1 was deleted would collide with
the row of the question that used to be number 2. Old code still reads both tables;
saving a note with it would fail (its ON CONFLICT names the old key).

How an old row finds its question: by its wording at the time (sitting snapshot,
answer snapshot, flag text, exclusion text). Exact match on today's wording, else
the decision table below, else -- for Modul 12, which counts for nothing -- removed.
Anything else STOPS the migration: guessing is never allowed. A removed question
gets an id of its own ("x-<hash>") that today's quiz does not contain, so it counts
for nobody while its points stay stored.

Usage:
    python migrate/migrate_085_frage_ids.py              # migrate config.DATABASE
    python migrate/migrate_085_frage_ids.py --probelauf  # count only, write nothing
    python migrate/migrate_085_frage_ids.py --probelauf path/to/copy.db
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

REMOVED = 'entfernt'

# (checkpoint_id, text_key(old wording)) -> today's position (1-based) or REMOVED.
# Decided by Patrick, 2026-11-24, one case at a time; numbers = rows of the table in
# docs/shared/lernmanager/2026-11-24-frage-ids-zuordnung.md
DECISIONS = {
    (605, '00db4b32e5d4'): 1,        # 1  1.3 Sulfat-Vergleich, genauer gefasst
    (605, '03c5748552c8'): 2,        # 2  1.3 Kontrollpaar -> heutige F2 (gleiche Denkaufgabe)
    (606, '9fbd9c619015'): 3,        # 3  1.4 Warum verschiedene Farben, + "Nenne beides"
    (606, 'f2f46e3aefcb'): REMOVED,  # 4  1.4 Blaues Licht: design_fehlerhaft, gelöscht
    (633, 'e9d32e3a946f'): 2,        # 5  1.7 Stärke des Modells
    (633, 'd0f3dab2a495'): 3,        # 6  1.7 Grenze des Modells (alte Lenkung = erste Grenze der neuen Rubrik)
    (633, 'd19df77c05c0'): REMOVED,  # 7  1.7 Eisenatom: design_fehlerhaft, gelöscht; F3 ist durch 6 belegt
    (666, 'e8c1d810ab5c'): 4,        # 13 3.2 Zink + Salzsäure, "geschlossen" -> "isochor"
    (667, '18668d0b6bf9'): 2,        # 14 3.3 Kalkofen: gleiche Optionen + Lösung, anderes Beispiel
    (667, 'edd68564ac27'): 4,        # 15 3.3 Zwei Paare, Schluss eindeutiger
    (668, '31eb7e8b1610'): 1,        # 16 3.4 Volumenarbeit, + "mit Vorzeichen" (offene Meldung)
}

# A decision names a checkpoint by id. Guard against ids that mean something else
# in the database this runs on: the heading must start like this.
EXPECTED_HEADINGS = {
    605: '### 1.3', 606: '### 1.4', 633: '### 1.7',
    666: '### 3.2', 667: '### 3.3', 668: '### 3.4',
    611: '### 12.2', 617: '### 12.8',
}

# Modul 12 counts for nothing (Patrick 2026-11-24: replaced by written answers).
# Old wordings there without an exact match are removed without a decision.
IGNORED_CHECKPOINTS = {611, 612, 613, 614, 615, 616, 617}
IGNORED_TASK_PREFIX = '12 -'


class Unresolved(Exception):
    pass


def norm(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def text_key(text):
    return hashlib.sha1(norm(text).encode('utf-8')).hexdigest()[:12]


def removed_id(text):
    return f'x-{text_key(text)}'


def assign_ids(questions):
    """Ids for today's questions: keep an existing one, else f<position>, skipping
    any f<n> already taken by an explicit id."""
    taken = {q['id'] for q in questions if q.get('id')}
    ids, n = [], 0
    for position, q in enumerate(questions, start=1):
        if q.get('id'):
            ids.append(q['id'])
            continue
        candidate = f'f{position}'
        while candidate in taken:
            n += 1
            candidate = f'f{position}-{n}'
        taken.add(candidate)
        ids.append(candidate)
    if len(set(ids)) != len(ids):
        raise Unresolved(f'doppelte id im aktuellen Quiz: {ids}')
    return ids


class Checkpoint:
    def __init__(self, row):
        self.id = row['id']
        self.heading = (row['beschreibung'] or '').split('\n')[0]
        self.task_name = row['task_name'] or ''
        self.quiz = json.loads(row['quiz_json'])
        self.questions = self.quiz.get('questions', [])
        self.ids = assign_ids(self.questions)
        by_text = {}
        for qid, q in zip(self.ids, self.questions):
            by_text.setdefault(norm(q.get('text')), []).append(qid)
        self.by_text = by_text

    @property
    def ignored(self):
        return self.id in IGNORED_CHECKPOINTS or self.task_name.startswith(IGNORED_TASK_PREFIX)

    def resolve(self, text):
        """(question_id, how) for an old wording. Raises Unresolved."""
        hits = self.by_text.get(norm(text), [])
        if len(hits) == 1:
            return hits[0], 'genau'
        if len(hits) > 1:
            raise Unresolved(f'Wortlaut kommt im aktuellen Quiz mehrfach vor: {norm(text)[:60]}')
        decision = DECISIONS.get((self.id, text_key(text)))
        if decision == REMOVED:
            return removed_id(text), 'entfernt'
        if decision is not None:
            if not 1 <= decision <= len(self.ids):
                raise Unresolved(f'Entscheidung zeigt auf F{decision}, Quiz hat {len(self.ids)} Fragen')
            return self.ids[decision - 1], 'tabelle'
        if self.ignored:
            return removed_id(text), 'modul12'
        raise Unresolved(f'keine Entscheidung für [{self.id}] {self.heading[:40]!r} '
                         f'key={text_key(text)}: {norm(text)[:80]!r}')

    def id_at(self, index):
        return self.ids[index] if index is not None and 0 <= index < len(self.ids) else None


def _snapshot_questions(raw):
    if not raw:
        return None
    try:
        return json.loads(raw).get('questions')
    except (TypeError, ValueError, AttributeError):
        return None


def build_plan(conn):
    """Work out every write without doing it. Returns (plan, stats, problems)."""
    conn.row_factory = sqlite3.Row
    stats, problems = {}, []
    count = lambda table, how: stats.setdefault(table, Counter()).update([how])

    checkpoints = {}
    for row in conn.execute('''
            SELECT s.id, s.beschreibung, s.quiz_json, t.name AS task_name
            FROM subtask s LEFT JOIN task t ON t.id = s.task_id
            WHERE s.checkpoint_type IS NOT NULL
              AND s.quiz_json IS NOT NULL AND s.quiz_json != '' '''):
        try:
            checkpoints[row['id']] = Checkpoint(row)
        except (ValueError, Unresolved) as e:
            problems.append(f'Checkpoint {row["id"]}: {e}')
    for cid, heading in EXPECTED_HEADINGS.items():
        if cid in checkpoints and not checkpoints[cid].heading.startswith(heading):
            problems.append(f'Checkpoint {cid} heißt {checkpoints[cid].heading!r}, '
                            f'die Entscheidungen meinen {heading!r}')

    plan = {'quiz': {}, 'attempt': {}, 'answer': {}, 'flag': {}, 'exclusion': {}, 'note': {}}

    def resolve(table, cp, text):
        try:
            qid, how = cp.resolve(text)
            count(table, how)
            return qid
        except Unresolved as e:
            problems.append(f'{table}: {e}')
            return None

    for cp in checkpoints.values():
        if any(not q.get('id') for q in cp.questions):
            quiz = dict(cp.quiz, questions=[dict(q, id=qid) for q, qid in zip(cp.questions, cp.ids)])
            plan['quiz'][cp.id] = json.dumps(quiz, ensure_ascii=False)

    # Sittings: the snapshot says what each position meant in THIS sitting.
    attempt_ids = {}
    for a in conn.execute('SELECT * FROM checkpoint_attempt'):
        cp = checkpoints.get(a['checkpoint_id'])
        snap = _snapshot_questions(a['quiz_snapshot_json'])
        has_scores = a['question_scores_json'] or a['question_scores_manual_json']
        if cp is None:
            if has_scores:
                problems.append(f'Sitzung {a["id"]}: Checkpoint {a["checkpoint_id"]} hat kein Quiz mehr')
            continue
        if snap is None:
            if has_scores:
                problems.append(f'Sitzung {a["id"]}: Punkte je Frage, aber kein Snapshot')
            continue
        ids = [resolve('sitzung_frage', cp, q.get('text')) for q in snap]
        seen = [i for i in ids if i]
        if len(seen) != len(set(seen)):
            problems.append(f'Sitzung {a["id"]}: zwei alte Fragen zeigen auf dieselbe id {ids}')
        attempt_ids[a['id']] = ids

        def rekey(raw):
            if not raw:
                return None
            out = {}
            for key, value in json.loads(raw).items():
                if not key.isdigit():
                    out[key] = value          # legacy 'vorher': not a question
                    continue
                index = int(key)
                if index >= len(ids) or ids[index] is None:
                    problems.append(f'Sitzung {a["id"]}: Punkte für Position {index} ohne Frage')
                    continue
                out[ids[index]] = value
            return json.dumps(out, ensure_ascii=False)

        snapshot = json.dumps(dict(json.loads(a['quiz_snapshot_json']),
                                   questions=[dict(q, id=qid) for q, qid in zip(snap, ids)]),
                              ensure_ascii=False)
        plan['attempt'][a['id']] = (rekey(a['question_scores_json']),
                                    rekey(a['question_scores_manual_json']), snapshot)
        for qid in ids:
            count('sitzung', 'mit_id' if qid else 'ohne_id')

    # Answers: their own snapshot (migrate_065) first, else their sitting's.
    for r in conn.execute('SELECT * FROM checkpoint_answer'):
        cp = checkpoints.get(r['checkpoint_id'])
        if cp is None:
            count('antwort', 'checkpoint_ohne_quiz')
            continue
        own = json.loads(r['question_snapshot_json']) if r['question_snapshot_json'] else None
        if own and own.get('text'):
            qid = resolve('antwort', cp, own['text'])
            own_out = json.dumps(dict(own, id=qid), ensure_ascii=False) if qid else None
        elif r['checkpoint_attempt_id'] in attempt_ids:
            ids = attempt_ids[r['checkpoint_attempt_id']]
            qid = ids[r['question_index']] if r['question_index'] < len(ids) else None
            count('antwort', 'über_sitzung' if qid else 'ohne_id')
            own_out = None
        elif r['checkpoint_attempt_id'] is None:
            # Unfinished sitting from before migrate_065: the wording is lost. These
            # rows carry no points; they stay without id instead of being guessed.
            qid, own_out = None, None
            count('antwort', 'ohne_wortlaut')
        else:
            qid, own_out = None, None
            problems.append(f'Antwort {r["id"]}: Sitzung {r["checkpoint_attempt_id"]} ohne Snapshot')
        plan['answer'][r['id']] = (qid, own_out)

    # Flags: wording at flag time, else the sitting's snapshot.
    for f in conn.execute('SELECT * FROM checkpoint_flag'):
        cp = checkpoints.get(f['checkpoint_id'])
        if cp is None:
            count('meldung', 'checkpoint_ohne_quiz')
            continue
        if norm(f['question_text_at_flag']):
            qid = resolve('meldung', cp, f['question_text_at_flag'])
        elif f['checkpoint_attempt_id'] in attempt_ids:
            ids = attempt_ids[f['checkpoint_attempt_id']]
            qid = ids[f['question_index']] if f['question_index'] < len(ids) else None
            count('meldung', 'über_sitzung')
        else:
            qid = None
        if qid is None:
            problems.append(f'Meldung {f["id"]} (Status {f["status"]}) bekommt keine id')
        plan['flag'][f['id']] = qid

    # Exclusions name today's wording; notes are about today's question (migrate_084).
    for x in conn.execute('SELECT * FROM checkpoint_question_exclusion'):
        cp = checkpoints.get(x['checkpoint_id'])
        if cp is None:
            continue
        qid = (resolve('ausschluss', cp, x['question_text']) if norm(x['question_text'])
               else cp.id_at(x['question_index']))
        if qid is None:
            problems.append(f'Ausschluss {x["checkpoint_id"]}/{x["question_index"]} bekommt keine id')
        plan['exclusion'][(x['checkpoint_id'], x['question_index'])] = qid
    exclusion_ids = [(cid, qid) for (cid, _), qid in plan['exclusion'].items() if qid]
    for key, n in Counter(exclusion_ids).items():
        if n > 1:
            problems.append(f'Ausschluss: zwei Zeilen in Checkpoint {key[0]} zeigen auf id {key[1]}')
    for n in conn.execute('SELECT * FROM checkpoint_question_note'):
        cp = checkpoints.get(n['checkpoint_id'])
        qid = cp.id_at(n['question_index']) if cp else None
        if qid is None:
            problems.append(f'Notiz {n["checkpoint_id"]}/{n["question_index"]} bekommt keine id')
        else:
            count('notiz', 'aktuelle_position')
        plan['note'][(n['checkpoint_id'], n['question_index'], n['admin_id'])] = qid

    return plan, stats, problems


def add_columns(conn):
    existing = lambda table: {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    statements = {
        ('checkpoint_attempt', 'question_scores_by_id_json'):
            'ALTER TABLE checkpoint_attempt ADD COLUMN question_scores_by_id_json TEXT',
        ('checkpoint_attempt', 'question_scores_manual_by_id_json'):
            'ALTER TABLE checkpoint_attempt ADD COLUMN question_scores_manual_by_id_json TEXT',
        ('checkpoint_answer', 'question_id'):
            'ALTER TABLE checkpoint_answer ADD COLUMN question_id TEXT',
        ('checkpoint_flag', 'question_id'):
            'ALTER TABLE checkpoint_flag ADD COLUMN question_id TEXT',
        ('checkpoint_question_exclusion', 'question_id'):
            'ALTER TABLE checkpoint_question_exclusion ADD COLUMN question_id TEXT',
        ('checkpoint_question_note', 'question_id'):
            'ALTER TABLE checkpoint_question_note ADD COLUMN question_id TEXT',
    }
    for (table, column), sql in statements.items():
        if column not in existing(table):
            conn.execute(sql)


REKEYED_TABLES = {
    'checkpoint_question_exclusion': '''
        CREATE TABLE checkpoint_question_exclusion_new (
            checkpoint_id INTEGER NOT NULL,
            question_index INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            reason TEXT,
            question_text TEXT,
            created_at TEXT NOT NULL,
            created_by INTEGER,
            PRIMARY KEY (checkpoint_id, question_id)
        )''',
    'checkpoint_question_note': '''
        CREATE TABLE checkpoint_question_note_new (
            checkpoint_id INTEGER NOT NULL,
            question_index INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            admin_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (checkpoint_id, question_id, admin_id)
        )''',
}


def rekey_tables(conn):
    """Move the primary key of the two question tables from position to id.
    Runs after apply_plan: every row has its question_id by then."""
    for table, create in REKEYED_TABLES.items():
        info = conn.execute(f'PRAGMA table_info({table})').fetchall()
        if any(r[1] == 'question_id' and r[5] for r in info):
            continue   # already keyed on question_id
        conn.execute(f'DROP TABLE IF EXISTS {table}_new')
        conn.execute(create)
        names = ', '.join(r[1] for r in conn.execute(f'PRAGMA table_info({table}_new)'))
        conn.execute(f'INSERT INTO {table}_new ({names}) SELECT {names} FROM {table}')
        conn.execute(f'DROP TABLE {table}')
        conn.execute(f'ALTER TABLE {table}_new RENAME TO {table}')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_checkpoint_flag_question_id '
                 'ON checkpoint_flag(checkpoint_id, question_id)')


def apply_plan(conn, plan):
    for cid, quiz in plan['quiz'].items():
        conn.execute('UPDATE subtask SET quiz_json = ? WHERE id = ?', (quiz, cid))
    for aid, (scores, manual, snapshot) in plan['attempt'].items():
        conn.execute('UPDATE checkpoint_attempt SET question_scores_by_id_json = ?, '
                     'question_scores_manual_by_id_json = ?, quiz_snapshot_json = ? WHERE id = ?',
                     (scores, manual, snapshot, aid))
    for rid, (qid, own) in plan['answer'].items():
        if own is not None:
            conn.execute('UPDATE checkpoint_answer SET question_id = ?, question_snapshot_json = ? '
                         'WHERE id = ?', (qid, own, rid))
        else:
            conn.execute('UPDATE checkpoint_answer SET question_id = ? WHERE id = ?', (qid, rid))
    for fid, qid in plan['flag'].items():
        conn.execute('UPDATE checkpoint_flag SET question_id = ? WHERE id = ?', (qid, fid))
    for (cid, idx), qid in plan['exclusion'].items():
        conn.execute('UPDATE checkpoint_question_exclusion SET question_id = ? '
                     'WHERE checkpoint_id = ? AND question_index = ?', (qid, cid, idx))
    for (cid, idx, admin_id), qid in plan['note'].items():
        conn.execute('UPDATE checkpoint_question_note SET question_id = ? '
                     'WHERE checkpoint_id = ? AND question_index = ? AND admin_id = ?',
                     (qid, cid, idx, admin_id))


def report(stats, problems):
    for table, c in stats.items():
        print(f'  {table:15} ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items())))
    if problems:
        print(f'\n{len(problems)} Problem(e), Migration hält an:')
        for p in problems:
            print('  -', p)


def run(db_path=None, probelauf=False):
    """Returns True on success. Writes nothing when there is any problem."""
    db_path = db_path or config.DATABASE
    conn = sqlite3.connect(db_path)
    try:
        plan, stats, problems = build_plan(conn)
        print(f'{"Probelauf" if probelauf else "Migration"}: {db_path}')
        report(stats, problems)
        if problems:
            return False
        if probelauf:
            print('\nKeine Probleme. Probelauf: nichts geschrieben.')
            return True
    finally:
        conn.close()

    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    print(f'Backup created: {backup_path}')
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            add_columns(conn)
            apply_plan(conn, plan)
            rekey_tables(conn)
        print('Frage-IDs gesetzt.')
        return True
    finally:
        conn.close()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--probelauf']
    ok = run(args[0] if args else None, probelauf='--probelauf' in sys.argv)
    sys.exit(0 if ok else 1)
