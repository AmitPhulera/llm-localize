import doctest
import importlib
import importlib.util
import pkgutil

import pytest

import llm_localize

MODULES = [
    name for _, name, _ in pkgutil.walk_packages(llm_localize.__path__, "llm_localize.")
    if ".management." not in name
    and (importlib.util.find_spec("django") or not name.startswith("llm_localize.contrib.django"))
]


@pytest.mark.parametrize("module_name", MODULES)
def test_doctests(module_name):
    results = doctest.testmod(importlib.import_module(module_name))
    assert results.failed == 0
