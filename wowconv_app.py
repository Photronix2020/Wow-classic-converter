"""Entry point for the packaged executable.

No arguments (e.g. double-clicked): opens the window.
With arguments: behaves like `python -m wowconv`.
"""

import os
import sys

from wowconv.__main__ import main
from wowconv.gui import run

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # A windowed build has no console streams; keep print() from failing.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w")
        sys.exit(main())
    sys.exit(run())
