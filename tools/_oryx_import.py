"""Resolve legacy and package imports through Python's ordinary module locks."""
from importlib import import_module
from pathlib import Path
import sys


def bind(legacy, owner):
    source = str(Path(__file__).resolve().parents[1] / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    shim = sys.modules[legacy]

    # A cycle on this thread can hold the original shim before the owner has
    # finished executing. Keep that reference usable after initialization.
    # import_module handles circular and cross-thread initialization itself.
    def forward(name):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(import_module(owner), name)

    shim.__getattr__ = forward
    module = import_module(owner)
    sys.modules[legacy] = module
