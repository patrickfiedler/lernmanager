"""Work-step checkboxes are on by default (migrate_054).

The column DEFAULT stays 0 -- SQLite cannot change a column default without
rebuilding the table, which is not worth the risk on a live student table.
The default therefore lives in create_student(), and this is what pins it.
"""
import models


def test_a_new_student_gets_step_checkboxes_on(db):
    sid = models.create_student("Neu", "Kind", "neukind", "pw123")
    assert models.get_student(sid)['step_checkboxes'] == 1


def test_a_student_can_still_switch_them_off(db):
    sid = models.create_student("Neu", "Kind", "neukind", "pw123")
    models.update_student_setting(sid, 'step_checkboxes', 0)
    assert models.get_student(sid)['step_checkboxes'] == 0
