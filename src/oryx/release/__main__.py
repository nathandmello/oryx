"""Installed Core distribution, receipt and recovery interface."""
import sys
from .channel import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        sys.exit(f"Oryx release: {exc}")
