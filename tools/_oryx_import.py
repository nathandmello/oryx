"""Preserve the identity of legacy imports for installed packages and existing callers."""
from importlib.util import find_spec, module_from_spec
from pathlib import Path
import sys


def bind(legacy, owner):
    source = str(Path(__file__).resolve().parents[1] / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    if owner in sys.modules:
        sys.modules[legacy] = sys.modules[owner]
        return
    spec = find_spec(owner)
    if spec is None or spec.loader is None:
        raise ImportError(f"Missing installed Oryx component {owner}")
    module = module_from_spec(spec)
    previous = sys.modules[legacy]
    sys.modules[legacy] = sys.modules[owner] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules[legacy] = previous
        del sys.modules[owner]
        raise
    # Direct import of the qualified child has normal package attribute semantics.
    parent, child = owner.rsplit(".", 1)
    setattr(sys.modules[parent], child, module)
