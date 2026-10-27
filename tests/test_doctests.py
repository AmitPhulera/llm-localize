import doctest
import importlib
import pkgutil

import pytest

import llm_localize

MODULES = [name for _, name, _ in pkgutil.walk_packages(llm_localize.__path__, "llm_localize.")]


@pytest.mark.parametrize("module_name", MODULES)
def test_doctests(module_name):
    results = doctest.testmod(importlib.import_module(module_name))
    assert results.failed == 0
