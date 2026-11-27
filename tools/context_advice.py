"""Compatibility entry for oryx.adapters.context_advice."""
from pathlib import Path
import sys

if (Path(__file__).resolve().parents[1] / "oryx-release-manifest.json").is_file():
    sys.dont_write_bytecode = True

from _oryx_import import bind

if __name__ == "__main__":
    bind(__name__, "oryx.adapters.context_advice")
    raise SystemExit(sys.modules[__name__].main())
else:
    bind(__name__, "oryx.adapters.context_advice")
