"""Smoke test: verify the package imports and exposes a version string."""

import corphish


def test_version_is_string():
    assert isinstance(corphish.__version__, str)


def test_version_is_not_empty():
    assert corphish.__version__ != ""
