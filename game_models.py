"""
Game mode database functions and game mechanics.
"""
import json
import random
from datetime import datetime, timedelta
from models import db_session
import config

# ============ Game Constants ============

# XP required for each level (cumulative)
XP_TABLE = [0, 100, 250, 500, 850, 1300, 1850, 2500, 3250, 4100, 5050]

# HP increase per level
HP_PER_LEVEL = 10
BASE_HP = 100

# XP rewards based on question source and difficulty
XP_REWARDS = {
    'current_task': {1: 20, 2: 25, 3: 30, 4: 40, 5: 50},
    'repetition': {1: 10, 2: 12, 3: 15, 4: 20, 5: 25},
    'random': {1: 15, 2: 18, 3: 22, 4: 28, 5: 35}
}

# HP damage for wrong answers (based on difficulty)
HP_DAMAGE = {1: 5, 2: 10, 3: 15, 4: 20, 5: 25}

# Area configuration
AREAS = {
    'village': {
        'name': 'Startdorf',
        'safe': True,
        'difficulty': 0,
        'encounter_rate': 0,
        'exits': ['meadow', 'forest']
    },
    'meadow': {
        'name': 'Wiese der Anfaenger',
        'safe': False,
        'difficulty': 1,
        'encounter_rate': 0.15,
        'exits': ['village']
    },
    'forest': {
        'name': 'Wald der Mysterien',
        'safe': False,
        'difficulty': 2,
        'encounter_rate': 0.20,
        'exits': ['village', 'mountain', 'cave']
    },
    'mountain': {
        'name': 'Berg der Herausforderungen',
        'safe': False,
        'difficulty': 4,
        'encounter_rate': 0.25,
        'exits': ['forest']
    },
    'cave': {
        'name': 'Hoehle des Wissens',
        'safe': False,
        'difficulty': 3,
        'encounter_rate': 0.22,
        'exits': ['forest']
    }
}

# Difficulty mapping from Stufe to game difficulty (1-5)
STUFE_TO_DIFFICULTY = {
    '5/6': 1,
    '7/8': 2,
    '9/10': 3,
    '11s': 4,
    '11/12': 5
}

# Monster types by difficulty
MONSTERS = {
    1: ['Schleim', 'Pilzling', 'Nebelwicht'],
    2: ['Waldgeist', 'Schattenkatze', 'Irrwurm'],
    3: ['Felsengolem', 'Dunkelelf', 'Frostwolf'],
    4: ['Sturmdrache', 'Feuerdaemon', 'Schattenlord'],
    5: ['Uralter Wyrm', 'Lichkoenig', 'Chaosbestie']
}


# ============ Character Functions ============

def get_character(student_id):
    """Get game character for a student."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM game_character WHERE student_id = ?",
            (student_id,)
        ).fetchone()
        return dict(row) if row else None


def create_character(student_id, fach):
    """Create a new game character for a student."""
    with db_session() as conn:
        conn.execute('''
            INSERT INTO game_character (student_id, fach, hp, max_hp, xp, level, current_area)
            VALUES (?, ?, ?, ?, 0, 1, 'village')
        ''', (student_id, fach, BASE_HP, BASE_HP))

        # Sync question pool for this student's subject
        sync_question_pool(student_id, fach)

        return get_character(student_id)


def delete_character(student_id):
    """Delete a game character (disable game mode)."""
    with db_session() as conn:
        conn.execute("DELETE FROM game_character WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM game_question_history WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM game_task_progress WHERE student_id = ?", (student_id,))


def update_character_position(student_id, area, x=0, y=0):
    """Update character's current area and position."""
    with db_session() as conn:
        conn.execute('''
            UPDATE game_character
            SET current_area = ?, position_x = ?, position_y = ?
            WHERE student_id = ?
        ''', (area, x, y, student_id))


def calculate_level(xp):
    """Calculate level from XP."""
    for level, required in enumerate(XP_TABLE):
        if xp < required:
            return max(1, level)
    return len(XP_TABLE)


def xp_for_next_level(current_xp):
    """Calculate XP needed for next level."""
    level = calculate_level(current_xp)
    if level >= len(XP_TABLE):
        return 0
    return XP_TABLE[level] - current_xp


def add_xp(student_id, xp_amount):
    """Add XP to character, handle level up."""
    with db_session() as conn:
        char = conn.execute(
            "SELECT xp, level, max_hp FROM game_character WHERE student_id = ?",
            (student_id,)
        ).fetchone()

        if not char:
            return None

        old_level = char['level']
        new_xp = char['xp'] + xp_amount
        new_level = calculate_level(new_xp)

        level_up = new_level > old_level
        new_max_hp = BASE_HP + (new_level - 1) * HP_PER_LEVEL

        conn.execute('''
            UPDATE game_character
            SET xp = ?, level = ?, max_hp = ?
            WHERE student_id = ?
        ''', (new_xp, new_level, new_max_hp, student_id))

        return {
            'new_xp': new_xp,
            'new_level': new_level,
            'level_up': level_up,
            'xp_to_next': xp_for_next_level(new_xp)
        }


def reduce_hp(student_id, damage):
    """Reduce character HP, check for defeat."""
    with db_session() as conn:
        char = conn.execute(
            "SELECT hp FROM game_character WHERE student_id = ?",
            (student_id,)
        ).fetchone()

        if not char:
            return None

        new_hp = max(0, char['hp'] - damage)
        defeated = new_hp <= 0

        conn.execute(
            "UPDATE game_character SET hp = ? WHERE student_id = ?",
            (new_hp, student_id)
        )

        return {'new_hp': new_hp, 'defeated': defeated}


def restore_hp(student_id, full=True):
    """Restore character HP (at village)."""
    with db_session() as conn:
        if full:
            conn.execute('''
                UPDATE game_character SET hp = max_hp, current_area = 'village'
                WHERE student_id = ?
            ''', (student_id,))
        else:
            # Partial restore (50%)
            conn.execute('''
                UPDATE game_character SET hp = MIN(max_hp, hp + max_hp / 2)
                WHERE student_id = ?
            ''', (student_id,))


# ============ Question Pool Functions ============

def sync_question_pool(student_id, fach):
    """Sync questions from completed tasks into game question pool."""
    with db_session() as conn:
        # Get all tasks with quizzes for this subject (completed or current)
        tasks = conn.execute('''
            SELECT DISTINCT t.id, t.quiz_json, t.stufe, t.fach
            FROM task t
            WHERE t.fach = ?
              AND t.quiz_json IS NOT NULL
        ''', (fach,)).fetchall()

        for task in tasks:
            if not task['quiz_json']:
                continue

            try:
                quiz = json.loads(task['quiz_json'])
            except json.JSONDecodeError:
                continue

            difficulty = STUFE_TO_DIFFICULTY.get(task['stufe'], 2)

            for idx, q in enumerate(quiz.get('questions', [])):
                conn.execute('''
                    INSERT OR REPLACE INTO game_question_pool
                    (task_id, question_index, question_text, answers_json,
                     correct_indices_json, difficulty, fach)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task['id'],
                    idx,
                    q.get('question', ''),
                    json.dumps(q.get('answers', [])),
                    json.dumps(q.get('correct', [])),
                    difficulty,
                    task['fach']
                ))


def get_question_count(student_id, fach):
    """Get count of available questions for a subject."""
    with db_session() as conn:
        result = conn.execute('''
            SELECT COUNT(*) as count FROM game_question_pool WHERE fach = ?
        ''', (fach,)).fetchone()
        return result['count'] if result else 0


def select_question(student_id, area_difficulty, fach):
    """
    Select appropriate question for encounter.

    Priority:
    1. 30% chance: Question from current active task
    2. 50% chance: Question due for spaced repetition
    3. 20% chance: Random from pool
    """
    with db_session() as conn:
        # Determine difficulty range based on area
        min_diff = max(1, area_difficulty - 1)
        max_diff = min(5, area_difficulty + 1)

        roll = random.random()

        # Try current task (30% chance)
        if roll < 0.30:
            question = get_current_task_question(conn, student_id, fach, min_diff, max_diff)
            if question:
                return dict(question), 'current_task'

        # Try spaced repetition (50% chance)
        if roll < 0.80:
            question = get_repetition_question(conn, student_id, fach, min_diff, max_diff)
            if question:
                return dict(question), 'repetition'

        # Fallback to random
        question = get_random_question(conn, student_id, fach, min_diff, max_diff)
        if question:
            return dict(question), 'random'

        # Ultimate fallback: any question from the subject
        question = conn.execute('''
            SELECT * FROM game_question_pool
            WHERE fach = ?
            ORDER BY RANDOM()
            LIMIT 1
        ''', (fach,)).fetchone()

        return (dict(question), 'random') if question else (None, None)


def get_current_task_question(conn, student_id, fach, min_diff, max_diff):
    """Get question from student's current active task."""
    return conn.execute('''
        SELECT qp.* FROM game_question_pool qp
        JOIN student_task st ON qp.task_id = st.task_id
        JOIN task t ON st.task_id = t.id
        WHERE st.student_id = ?
          AND st.abgeschlossen = 0
          AND t.fach = ?
          AND qp.difficulty BETWEEN ? AND ?
        ORDER BY RANDOM()
        LIMIT 1
    ''', (student_id, fach, min_diff, max_diff)).fetchone()


def get_repetition_question(conn, student_id, fach, min_diff, max_diff):
    """Get question due for spaced repetition review."""
    return conn.execute('''
        SELECT qp.* FROM game_question_pool qp
        LEFT JOIN game_question_history qh
            ON qp.id = qh.question_pool_id AND qh.student_id = ?
        WHERE qp.fach = ?
          AND qp.difficulty BETWEEN ? AND ?
          AND (qh.next_review IS NULL OR qh.next_review <= datetime('now'))
        ORDER BY
            qh.next_review ASC NULLS FIRST,
            RANDOM()
        LIMIT 1
    ''', (student_id, fach, min_diff, max_diff)).fetchone()


def get_random_question(conn, student_id, fach, min_diff, max_diff):
    """Get random question from pool."""
    return conn.execute('''
        SELECT * FROM game_question_pool
        WHERE fach = ?
          AND difficulty BETWEEN ? AND ?
        ORDER BY RANDOM()
        LIMIT 1
    ''', (fach, min_diff, max_diff)).fetchone()


def record_answer(student_id, question_pool_id, correct):
    """Record answer in question history for spaced repetition."""
    with db_session() as conn:
        # Get existing history
        history = conn.execute('''
            SELECT * FROM game_question_history
            WHERE student_id = ? AND question_pool_id = ?
        ''', (student_id, question_pool_id)).fetchone()

        now = datetime.now()

        if history:
            times_answered = history['times_answered'] + 1
            times_correct = history['times_correct'] + (1 if correct else 0)

            # Calculate next review using spaced repetition
            if correct:
                # Increase interval based on success rate
                success_rate = times_correct / times_answered
                days = int(1 + success_rate * times_correct * 2)
                next_review = now + timedelta(days=min(days, 30))
            else:
                # Review soon if wrong
                next_review = now + timedelta(hours=4)

            conn.execute('''
                UPDATE game_question_history
                SET times_answered = ?, times_correct = ?,
                    last_answered = ?, next_review = ?
                WHERE student_id = ? AND question_pool_id = ?
            ''', (times_answered, times_correct, now.isoformat(),
                  next_review.isoformat(), student_id, question_pool_id))
        else:
            # First time answering
            next_review = now + timedelta(days=1 if correct else 0, hours=0 if correct else 4)
            conn.execute('''
                INSERT INTO game_question_history
                (student_id, question_pool_id, times_answered, times_correct,
                 last_answered, next_review)
                VALUES (?, ?, 1, ?, ?, ?)
            ''', (student_id, question_pool_id, 1 if correct else 0,
                  now.isoformat(), next_review.isoformat()))


# ============ Task Progress Functions ============

def record_game_task_progress(student_id, question_pool_id, correct):
    """Record game answer toward real task completion."""
    if not correct:
        return None

    with db_session() as conn:
        # Get the question's task info
        question = conn.execute('''
            SELECT task_id, question_index FROM game_question_pool WHERE id = ?
        ''', (question_pool_id,)).fetchone()

        if not question:
            return None

        # Find student's active task for this task_id
        student_task = conn.execute('''
            SELECT id FROM student_task
            WHERE student_id = ? AND task_id = ? AND abgeschlossen = 0
        ''', (student_id, question['task_id'])).fetchone()

        if not student_task:
            return None

        # Record progress
        conn.execute('''
            INSERT OR REPLACE INTO game_task_progress
            (student_id, student_task_id, question_index, answered_correctly)
            VALUES (?, ?, ?, 1)
        ''', (student_id, student_task['id'], question['question_index']))

        # Check task completion status
        task = conn.execute('''
            SELECT t.quiz_json FROM task t
            JOIN student_task st ON t.id = st.task_id
            WHERE st.id = ?
        ''', (student_task['id'],)).fetchone()

        if not task or not task['quiz_json']:
            return None

        quiz = json.loads(task['quiz_json'])
        total_questions = len(quiz.get('questions', []))

        correct_count = conn.execute('''
            SELECT COUNT(*) as count FROM game_task_progress
            WHERE student_task_id = ? AND answered_correctly = 1
        ''', (student_task['id'],)).fetchone()['count']

        return {
            'student_task_id': student_task['id'],
            'questions_answered': correct_count,
            'questions_total': total_questions,
            'can_complete': correct_count >= total_questions
        }


# ============ Combat Functions ============

def get_monster_for_area(area_key):
    """Get a random monster for the given area."""
    area = AREAS.get(area_key)
    if not area or area['safe']:
        return None

    difficulty = area['difficulty']
    monsters = MONSTERS.get(difficulty, MONSTERS[1])
    return random.choice(monsters)


def check_encounter(area_key):
    """Check if a random encounter should occur."""
    area = AREAS.get(area_key)
    if not area or area['safe']:
        return False

    return random.random() < area['encounter_rate']


def calculate_xp_reward(source, difficulty):
    """Calculate XP reward for correct answer."""
    rewards = XP_REWARDS.get(source, XP_REWARDS['random'])
    return rewards.get(difficulty, rewards[1])


def calculate_hp_damage(difficulty):
    """Calculate HP damage for wrong answer."""
    return HP_DAMAGE.get(difficulty, HP_DAMAGE[1])
