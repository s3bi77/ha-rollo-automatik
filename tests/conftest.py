"""Gemeinsame Test-Fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Lädt die Integration aus custom_components."""
    yield
