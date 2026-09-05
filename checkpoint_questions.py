"""Checkpoint review, seen per QUESTION instead of per student session.

The review page groups by session because grading is per student. But "is this
question broken?" is a claim about the question across the whole class, and answering
it from a session list means opening every session and holding the pattern in your
head. This module re-groups the same display model
(app._build_checkpoint_sessions) along the other axis.

Three independent detectors, deliberately NOT merged into one suspicion score:

  1. failure / report / give-up rate -- something went wrong here, for how many
  2. failure CLUSTERING              -- they went wrong the SAME way
  3. grader confidence               -- how often the model hesitated (migrate_052)

Merging them would destroy the distinction that decides what to do with a question.
A shared failure can mean the question is broken OR that the class has not learnt the
material, and those need opposite responses -- the first is a repair, the second is a
finding for the next lesson. Nothing here decides between them; it puts the evidence
in one place so a teacher can.

Detector 3 is the weakest and is labelled as such in the UI. As of 2026-09-04 there
is no evidence that per-question confidence says anything about question quality --
see the UNSURE_CONFIDENCE block below for what was measured and what came back flat.
It is displayed because it is cheap and already recorded, not because it is trusted.

Everything here is read-only aggregation over data the review page already loaded.
No queries, no writes -- so a teacher can look without any risk to a grade.
"""
import collections
import re

# Two failing students who fail *differently* are not evidence about the question.
# Below this many, the cluster line is suppressed rather than shown at n=1, where it
# would dress a single student's answer up as a pattern.
MIN_CLUSTER_SIZE = 2

# Jaccard overlap of content words at which two students' feedback counts as "the
# same complaint". Read off the 2026-08/09 exports (see
# scripts/checkpoint_cluster_eval.py): 0.25 separated the real cases -- 12.2 Q3 at
# 4-of-5 sharing falsch/kathode/minuspol, 12.3 Q1 at 3-of-3 -- from questions whose
# failures were genuinely unrelated. It is a starting value read off 49 sessions,
# not an established one; the eval script re-derives it against new data.
CLUSTER_SIMILARITY = 0.25

# Below this, one judgment counts as "the grader was not sure of this one". 0.8 is
# migrate_052's provisional value and is NOT established -- it was read off 66
# replayed answers on the 12.2/12.3 question set, which has since been rewritten.
# Nothing gates on it: it decides display only, so a wrong threshold costs attention
# rather than anyone's grade.
UNSURE_CONFIDENCE = 0.8

# What the question view knows, as of 2026-09-04, about what that number MEANS:
#
#   * The signal has structure. 23 sub-0.8 judgments in the 2026-08/09 exports sit in
#     7 questions; 6 questions have none at all. That is not noise sprayed evenly.
#   * It is symmetric across verdicts -- median 0.994 where the grader said "richtig",
#     0.999 where it said "falsch", 11 vs 12 unsure judgments. So it is not the
#     artefact of a grader that is confidently harsh and hesitantly lenient.
#   * It does NOT predict which questions students report as broken. Grouped at 0.95
#     mean confidence: 46% vs 45% failure rate, 3/6 vs 3/7 with a failure cluster.
#     The one question with 8 student reports sits at 1.00; the one with the most
#     unsure judgments has zero reports.
#
# So: measured against the only proxy available without teacher labels, question-level
# confidence says nothing about question quality. It is surfaced as what it literally
# is -- "the grader hesitated here N times" -- and never as "this question is bad".
# The claim migrate_052 actually makes is about INDIVIDUAL judgments (0.997 median
# when the verdict matched the teacher, 0.731 when it did not), which a per-question
# average washes out and which cannot be re-tested until Phase 4 collects verdicts on
# low-confidence rows. See the module docstring.

# German function words plus the grader's own stock phrasing. Without this the top
# shared terms of every cluster are "antwort", "nicht", "geforderte" -- true of every
# rejection, and so evidence of nothing.
_STOPWORDS = frozenset('''
die der das ist und ein eine einen einem eines antwort antworten nicht aber zwar
den dem des zu von im in mit als auf fuer für sich wird werden wurde ist sind war
dass dass fehlt geforderte geforderten geforderter gefordert enthält enthaelt
nennt genannt zwar jedoch sondern oder auch noch nur schon sehr mehr dabei damit
somit daher deshalb weil denn wenn dann also zum zur bei bis aus vor nach über
unter durch gegen ohne um am an es sie er ihr ihre seinen seine dieser diese
dieses jener jene welche welcher hat haben habe kann koennen können muss müssen
'''.split())


def _content_terms(text):
    """Comparable content words of one feedback line.

    Length filter plus stopword list: what survives is the vocabulary that says WHAT
    was wrong ("kathode", "minuspol", "teilgleichung"), not the frame every rejection
    shares.
    """
    if not text:
        return set()
    words = re.sub(r'[^\w\säöüßÄÖÜΔ]', ' ', str(text).lower()).split()
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_failures(per_student_feedback):
    """Largest group of students whose failure feedback says the same thing.

    per_student_feedback: {student_id: [feedback strings]}.
    Returns {'size', 'student_ids', 'terms'} or None when nothing clusters.

    Greedy and deliberately simple: for each student, collect everyone whose terms
    overlap theirs past the threshold, and keep the biggest such group. Not proper
    clustering -- it can pick a slightly sub-optimal group -- but it is one pass, it
    needs no dependency, and the number it produces ("4 von 6 scheitern ähnlich") is
    a prompt to go and look, never an automatic verdict.

    IMPORTANT: give-up rows must be excluded by the caller. On a give-up the stored
    feedback is the model solution, identical for every student by construction, so
    including them makes every question cluster perfectly at 1.00 and the signal
    reads as maximally strong exactly where it is meaningless.
    """
    terms = {sid: set().union(*[_content_terms(f) for f in fb]) if fb else set()
             for sid, fb in per_student_feedback.items()}
    terms = {sid: t for sid, t in terms.items() if t}
    if len(terms) < MIN_CLUSTER_SIZE:
        return None

    best = []
    for anchor, anchor_terms in terms.items():
        group = [sid for sid, t in terms.items()
                 if _jaccard(anchor_terms, t) >= CLUSTER_SIMILARITY]
        if len(group) > len(best):
            best = group
    if len(best) < MIN_CLUSTER_SIZE:
        return None

    shared = set.intersection(*[terms[sid] for sid in best])
    return {
        'size': len(best),
        'student_ids': sorted(best),
        # Longest first: the specific words ("energieniveau") carry more than the
        # short ones ("pole") and are what makes the line readable at a glance.
        'terms': sorted(shared, key=lambda w: (-len(w), w))[:6],
    }


def _wording_variants(entries):
    """Distinct question wordings among these sessions, most common first.

    Exists because the (checkpoint, index) slot is NOT a stable identifier for a
    question: 6 of 24 slots in the 2026-08/09 production data carry more than one
    wording, and one checkpoint has sessions with 2, 0 and 3 questions. A batch keyed
    on the index alone would act on students who answered a different question.

    Ties break towards the most recent session, so a wording that has just replaced
    another wins once it is equally common.
    """
    by_text = collections.defaultdict(list)
    for entry, question in entries:
        by_text[question.get('question_text')].append(entry)
    variants = []
    for text, sessions in by_text.items():
        variants.append({
            'text': text,
            'attempt_ids': [e['attempt']['id'] for e in sessions],
            'session_count': len(sessions),
            'latest': max(e['attempt']['timestamp'] for e in sessions),
        })
    variants.sort(key=lambda v: (v['session_count'], v['latest']), reverse=True)
    return variants


def build_question_view(sessions):
    """Aggregate the session display model into one row per checkpoint question.

    `sessions` is exactly what app._build_checkpoint_sessions returns, so this view
    and the session view can never disagree about a score, a flag or a duplicate --
    there is one derivation and this re-reads it.

    Rows are ordered by suspicion (failure rate, then how many students saw it) so
    the questions worth opening come first.
    """
    grouped = collections.defaultdict(list)
    for entry in sessions:
        if entry['attempt'].get('superseded_at'):
            continue                    # a reset session is history, not evidence
        for question in entry['questions']:
            key = (entry['attempt']['checkpoint_id'], question['question_index'])
            grouped[key].append((entry, question))

    rows = [_build_row(checkpoint_id, question_index, entries)
            for (checkpoint_id, question_index), entries in grouped.items()]
    rows.sort(key=lambda r: (-r['concern_rate'], -r['concern_count'],
                             r['checkpoint_id'], r['question_index']))
    return rows


def _build_row(checkpoint_id, question_index, entries):
    """One question's aggregate. `entries` is [(session, question), ...]."""
    first_question = entries[0][1]
    variants = _wording_variants(entries)
    reference = variants[0]

    students, failed, gave_up, reported = set(), set(), set(), set()
    attempt_counts = []
    confidences, per_student_feedback = [], collections.defaultdict(list)
    open_flags = 0

    # Flags the teacher raised about the QUESTION carry no attempt and no student, so
    # app._build_checkpoint_sessions merges the same row into every session that
    # contains the question. Keyed by id here, or the mark a teacher set once would
    # be listed once per student who sat the checkpoint.
    teacher_flags = {}

    for entry, question in entries:
        student_id = entry['attempt']['student_id']
        students.add(student_id)
        open_flags += sum(1 for f in question.get('flags', [])
                          if f.get('status') == 'offen')
        for flag in question.get('flags', []):
            if flag.get('source') == 'teacher':
                teacher_flags[flag['id']] = flag

        graded = [a for a in question['answers'] if not a.get('gave_up')]
        attempt_counts.append(len(graded))
        if any(a.get('gave_up') for a in question['answers']):
            gave_up.add(student_id)
        # `scored` is None for a reported question -- no verdict yet, so it is neither
        # a pass nor a failure and must not be counted as either. It is counted as a
        # REPORT instead, which is a stronger signal than either: the student is
        # saying the question is broken in so many words. Derived from `scored` rather
        # than by reading the flag rows, so it follows exactly the rule the scoring
        # uses -- 22 of 202 questions in the 2026-08/09 exports are in this state and
        # every one of them carries a Meldung.
        if question['scored'] is None:
            reported.add(student_id)
        elif question['scored'] < 3:
            failed.add(student_id)

        for answer in graded:
            if answer.get('judgment_confidence') is not None:
                confidences.append(answer['judgment_confidence'])
            # Only the LAST wrong answer per student: an early wrong attempt that the
            # student then fixed is not what they failed on, and counting every
            # attempt would let one persistent student dominate the cluster. The
            # `is not None` guard keeps ungraded rows (LLM outage) out -- they carry
            # no verdict, so they are not a failure to explain.
            if answer.get('correct') is not None and not answer['correct'] \
                    and answer.get('feedback'):
                per_student_feedback[student_id] = [answer['feedback']]

    student_count = len(students)
    # Everyone this question went wrong for, in any of the three ways. The rate off
    # THIS is what orders the view: a question 8 of 12 students reported is the
    # strongest evidence available that it is broken, and ranking on failures alone
    # buried it (1.4 F2 sat 17th at 4/12 while carrying 8 reports). The three counts
    # stay separate in the row so the number is never a black box.
    concerned = failed | reported | gave_up
    return {
        'checkpoint_id': checkpoint_id,
        'question_index': question_index,
        'question_type': first_question.get('question_type'),
        'rubric': first_question.get('rubric'),
        'correct_display': first_question.get('correct_display'),
        'wording': reference['text'],
        'variants': variants,
        'has_drift': len(variants) > 1,
        'task_name': entries[0][0]['attempt'].get('task_name'),
        'subtask_name': entries[0][0]['attempt'].get('subtask_name'),
        'attempt_ids': reference['attempt_ids'],
        'divergent_attempt_ids': [aid for v in variants[1:] for aid in v['attempt_ids']],
        'student_count': student_count,
        'failed_count': len(failed),
        'failed_student_ids': sorted(failed),
        'gave_up_count': len(gave_up),
        'reported_count': len(reported),
        'concern_count': len(concerned),
        'concern_rate': (len(concerned) / student_count) if student_count else 0.0,
        'failure_rate': (len(failed) / student_count) if student_count else 0.0,
        # The population the cluster was actually drawn from: students with a graded
        # wrong answer on this question. NOT failed_count -- a reported question
        # carries wrong answers but no failure, so using failures as the denominator
        # printed impossible lines like "6 von 4 scheitern ähnlich".
        'clusterable_count': len(per_student_feedback),
        'mean_attempts': (sum(attempt_counts) / len(attempt_counts)) if attempt_counts else 0.0,
        'confidence_mean': (sum(confidences) / len(confidences)) if confidences else None,
        'confidence_min': min(confidences) if confidences else None,
        'confidence_n': len(confidences),
        # A COUNT, not the average. The average hides exactly the structure that
        # exists: 1.3 F1 has 7 unsure judgments out of 38 and still averages 0.92,
        # which reads as mild. "7 mal gezoegert" is the honest rendering, and it is a
        # statement about the grader, never about the question.
        'unsure_count': sum(1 for c in confidences if c < UNSURE_CONFIDENCE),
        'cluster': cluster_failures(per_student_feedback),
        'open_flag_count': open_flags,
        # Only the teacher's own marks. A student's report is answered per session --
        # it belongs to one sitting and is ruled on there, next to the answer that
        # prompted it. This one is a statement about the question, so it lives here.
        'teacher_flags': sorted(teacher_flags.values(),
                                key=lambda f: f['created_at'], reverse=True),
    }
