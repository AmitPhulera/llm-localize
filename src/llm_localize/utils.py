"""Small helpers shared across the package."""
import importlib


def import_class(dotted_path, base_class):
    """Import a class by dotted path and check it subclasses ``base_class``.

    Raises ``ImportError`` if it can't be imported or has the wrong type.
    """
    module_path, _, class_name = dotted_path.rpartition('.')
    if not module_path:
        raise ImportError(f"{dotted_path!r} is not a dotted path")
    try:
        cls = getattr(importlib.import_module(module_path), class_name)
    except AttributeError as e:
        raise ImportError(f"{module_path} has no attribute {class_name!r}") from e
    if not (isinstance(cls, type) and issubclass(cls, base_class)):
        raise ImportError(f"{dotted_path} is not a {base_class.__name__} subclass")
    return cls
