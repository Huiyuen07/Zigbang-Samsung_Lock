"""Shared fixtures: let Home Assistant load the custom integration in tests."""
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """pytest-homeassistant-custom-component 預設不載入 custom_components。"""
    yield
