"""Compatibility entry for oryx.cli.command."""
from pathlib import Path
import sys

if (Path(__file__).resolve().parents[1] / "oryx-release-manifest.json").is_file():
    sys.dont_write_bytecode = True

from _oryx_import import bind

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from oryx.cli.application import main
    raise SystemExit(main(root))
else:
    bind(__name__, "oryx.cli.command")
