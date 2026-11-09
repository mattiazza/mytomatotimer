"""Milestone 0: proves the package is importable and pytest is wired up."""

import mytomatotimer


def test_package_imports():
    assert mytomatotimer.__version__ == "0.1.0"
