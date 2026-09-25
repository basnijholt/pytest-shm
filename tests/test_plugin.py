"""Behavior of the pytest-shm plugin, observed through real pytest sessions."""

from __future__ import annotations

import pytest


def test_plugin_is_registered(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("shm")
