"""
Game mode Flask routes and API endpoints.
"""
import json
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

import config
import models
import game_models

game_bp = Blueprint('game', __name__)


def student_required(f):
    """Decorator to require student login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'student_id' not in session:
            flash('Bitte melden Sie sich an.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ============ Game Mode Views ============

@game_bp.route('/schueler/game')
@student_required
def game_view():
    """Main game view - render Phaser canvas."""
    student_id = session['student_id']
    character = game_models.get_character(student_id)

    if not character:
        # Redirect to setup if no character exists
        return redirect(url_for('game.game_setup'))

    return render_template('student/game.html', character=character)


@game_bp.route('/schueler/game/setup', methods=['GET', 'POST'])
@student_required
def game_setup():
    """Game setup - choose subject."""
    student_id = session['student_id']

    # Check if already has character
    character = game_models.get_character(student_id)
    if character:
        return redirect(url_for('game.game_view'))

    if request.method == 'POST':
        fach = request.form.get('fach')
        if fach and fach in config.SUBJECTS:
            game_models.create_character(student_id, fach)
            flash(f'Willkommen im Spiel! Dein Fach: {fach}', 'success')
            return redirect(url_for('game.game_view'))
        flash('Bitte waehle ein Fach.', 'warning')

    return render_template('student/game_setup.html', subjects=config.SUBJECTS)


@game_bp.route('/schueler/game/disable', methods=['POST'])
@student_required
def game_disable():
    """Disable game mode and delete character."""
    student_id = session['student_id']
    game_models.delete_character(student_id)
    flash('Spielmodus deaktiviert.', 'info')
    return redirect(url_for('student_dashboard'))


# ============ Game State API ============

@game_bp.route('/api/game/state')
@student_required
def api_game_state():
    """Get current game state."""
    student_id = session['student_id']
    character = game_models.get_character(student_id)

    if not character:
        return jsonify({'error': 'No character found'}), 404

    # Get question count
    question_count = game_models.get_question_count(student_id, character['fach'])

    # Get current active tasks
    klassen = models.get_student_klassen(student_id)
    active_tasks = []
    for klasse in klassen:
        task = models.get_student_task(student_id, klasse['id'])
        if task and not task['abgeschlossen']:
            active_tasks.append({
                'klasse': klasse['name'],
                'task_name': task['name'],
                'fach': task['fach']
            })

    return jsonify({
        'character': {
            'fach': character['fach'],
            'hp': character['hp'],
            'max_hp': character['max_hp'],
            'xp': character['xp'],
            'xp_to_next': game_models.xp_for_next_level(character['xp']),
            'level': character['level'],
            'area': character['current_area'],
            'position': {
                'x': character['position_x'],
                'y': character['position_y']
            }
        },
        'available_questions': question_count,
        'active_tasks': active_tasks,
        'areas': game_models.AREAS
    })


@game_bp.route('/api/game/move', methods=['POST'])
@student_required
def api_game_move():
    """Update character position and check for encounters."""
    student_id = session['student_id']
    data = request.get_json()

    area = data.get('area')
    x = data.get('x', 0)
    y = data.get('y', 0)

    if area not in game_models.AREAS:
        return jsonify({'error': 'Invalid area'}), 400

    game_models.update_character_position(student_id, area, x, y)

    # Check for random encounter
    encounter = game_models.check_encounter(area)

    result = {
        'area': area,
        'position': {'x': x, 'y': y},
        'encounter': encounter
    }

    if encounter:
        monster = game_models.get_monster_for_area(area)
        result['monster'] = monster
        result['area_difficulty'] = game_models.AREAS[area]['difficulty']

    return jsonify(result)


# ============ Encounter API ============

@game_bp.route('/api/game/encounter/question')
@student_required
def api_encounter_question():
    """Get a question for the current encounter."""
    student_id = session['student_id']
    character = game_models.get_character(student_id)

    if not character:
        return jsonify({'error': 'No character found'}), 404

    area = character['current_area']
    area_data = game_models.AREAS.get(area, game_models.AREAS['meadow'])
    difficulty = area_data['difficulty']

    question, source = game_models.select_question(
        student_id, difficulty, character['fach']
    )

    if not question:
        return jsonify({'error': 'No questions available'}), 404

    # Parse answers
    answers = json.loads(question['answers_json'])
    correct = json.loads(question['correct_indices_json'])

    return jsonify({
        'question_id': question['id'],
        'text': question['question_text'],
        'answers': answers,
        'multiple': len(correct) > 1,
        'source': source,
        'difficulty': question['difficulty']
    })


@game_bp.route('/api/game/encounter/answer', methods=['POST'])
@student_required
def api_encounter_answer():
    """Submit an answer for the current encounter."""
    student_id = session['student_id']
    character = game_models.get_character(student_id)

    if not character:
        return jsonify({'error': 'No character found'}), 404

    data = request.get_json()
    question_id = data.get('question_id')
    answer_indices = data.get('answer_indices', [])

    # Get the question
    with models.db_session() as conn:
        question = conn.execute(
            "SELECT * FROM game_question_pool WHERE id = ?",
            (question_id,)
        ).fetchone()

    if not question:
        return jsonify({'error': 'Question not found'}), 404

    # Check answer
    correct_indices = json.loads(question['correct_indices_json'])
    is_correct = set(answer_indices) == set(correct_indices)

    # Record in history for spaced repetition
    game_models.record_answer(student_id, question_id, is_correct)

    result = {
        'correct': is_correct,
        'correct_indices': correct_indices
    }

    difficulty = question['difficulty']

    if is_correct:
        # Award XP
        source = data.get('source', 'random')
        xp_reward = game_models.calculate_xp_reward(source, difficulty)
        xp_result = game_models.add_xp(student_id, xp_reward)

        result['xp_gained'] = xp_reward
        result['level_up'] = xp_result['level_up'] if xp_result else False
        result['new_level'] = xp_result['new_level'] if xp_result else None
        result['hp_change'] = 0

        # Check task progress
        task_progress = game_models.record_game_task_progress(
            student_id, question_id, True
        )
        if task_progress:
            result['task_progress'] = task_progress
    else:
        # Reduce HP
        damage = game_models.calculate_hp_damage(difficulty)
        hp_result = game_models.reduce_hp(student_id, damage)

        result['xp_gained'] = 0
        result['hp_change'] = -damage
        result['defeated'] = hp_result['defeated'] if hp_result else False
        result['new_hp'] = hp_result['new_hp'] if hp_result else 0

    return jsonify(result)


# ============ Village API ============

@game_bp.route('/api/game/village/rest', methods=['POST'])
@student_required
def api_village_rest():
    """Rest at village to restore HP."""
    student_id = session['student_id']
    character = game_models.get_character(student_id)

    if not character:
        return jsonify({'error': 'No character found'}), 404

    if character['current_area'] != 'village':
        return jsonify({'error': 'Must be in village to rest'}), 400

    game_models.restore_hp(student_id, full=True)

    # Get updated character
    character = game_models.get_character(student_id)

    return jsonify({
        'hp': character['hp'],
        'max_hp': character['max_hp'],
        'message': 'Vollstaendig erholt!'
    })


@game_bp.route('/api/game/village/return', methods=['POST'])
@student_required
def api_village_return():
    """Return to village (after defeat or manually)."""
    student_id = session['student_id']

    game_models.restore_hp(student_id, full=True)

    return jsonify({
        'message': 'Zurueck im Dorf',
        'area': 'village'
    })


@game_bp.route('/api/game/sync-questions', methods=['POST'])
@student_required
def api_sync_questions():
    """Manually sync question pool."""
    student_id = session['student_id']
    character = game_models.get_character(student_id)

    if not character:
        return jsonify({'error': 'No character found'}), 404

    game_models.sync_question_pool(student_id, character['fach'])
    count = game_models.get_question_count(student_id, character['fach'])

    return jsonify({
        'message': 'Fragen synchronisiert',
        'question_count': count
    })
