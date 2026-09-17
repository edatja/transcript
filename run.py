#!/usr/bin/env python3
"""Entry point.  Run `python3 run.py` from the project root.

Adds src/ to the import path so the project works straight out of a clone,
with no `pip install -e .` step -- one less thing to go wrong.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from irs_transcript.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
