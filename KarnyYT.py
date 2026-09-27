#!/usr/bin/env python3
"""KarnyYT - punkt wejścia (dev: `python KarnyYT.py`, build: PyInstaller)."""

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from karnyyt.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
