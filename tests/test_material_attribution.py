"""Regression test: material attribution round-trips through create + export
and renders on the admin task detail page.
"""
import models


def test_attribution_stored_and_exported(db):
    task_id = models.create_task("Testthema", "", "", "MBI", "5/6", "pflicht")
    models.create_material(task_id, "link", "https://example.com/foto.jpg",
                            "Beispielfoto", attribution="Max Mustermann")

    materials = models.get_materials(task_id)
    assert materials[0]["attribution"] == "Max Mustermann"

    exported = models.export_task_to_dict(task_id)
    assert exported["materials"][0]["attribution"] == "Max Mustermann"


def test_attribution_optional(db):
    task_id = models.create_task("Testthema", "", "", "MBI", "5/6", "pflicht")
    models.create_material(task_id, "link", "https://example.com", "Ohne Quelle")

    materials = models.get_materials(task_id)
    assert materials[0]["attribution"] is None


def test_attribution_renders_on_admin_page(as_admin):
    task_id = models.create_task("Testthema", "", "", "MBI", "5/6", "pflicht")
    models.create_material(task_id, "link", "https://example.com/foto.jpg",
                            "Beispielfoto", attribution="Max Mustermann")

    resp = as_admin.get(f"/admin/thema/{task_id}")
    assert resp.status_code == 200
    assert "Max Mustermann" in resp.get_data(as_text=True)
