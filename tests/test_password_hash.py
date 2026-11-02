"""The production password hash. All other tests run on a cheap one (conftest.py),
so this file is the only place that notices a weakened or broken hash."""
import pytest

import models

pytestmark = pytest.mark.real_hash


def test_new_hashes_use_scrypt():
    assert models.hash_password("geheim").startswith("scrypt:")


def test_right_password_passes():
    assert models.verify_password(models.hash_password("geheim"), "geheim") == (True, False)


def test_wrong_password_fails():
    assert models.verify_password(models.hash_password("geheim"), "falsch") == (False, False)


def test_legacy_sha256_hash_passes_and_asks_for_rehash():
    legacy = models._legacy_hash("geheim")
    assert models.verify_password(legacy, "geheim") == (True, True)
    assert models.verify_password(legacy, "falsch") == (False, False)
