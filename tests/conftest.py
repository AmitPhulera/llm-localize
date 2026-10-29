import importlib.util

import pytest

# Lets the core suite run where Django isn't installed (with -p no:django)
if importlib.util.find_spec("django") is None:
    collect_ignore = ["django_integration"]


@pytest.fixture(autouse=True)
def no_generic_api_key(monkeypatch):
    """Keep a developer's own ``LLM_LOCALIZE_API_KEY`` from leaking into tests."""
    monkeypatch.delenv("LLM_LOCALIZE_API_KEY", raising=False)
