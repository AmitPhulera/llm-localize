import pytest


@pytest.fixture(autouse=True)
def no_generic_api_key(monkeypatch):
    """Keep a developer's own ``LLM_LOCALIZE_API_KEY`` from leaking into tests."""
    monkeypatch.delenv("LLM_LOCALIZE_API_KEY", raising=False)
