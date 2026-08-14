from __future__ import annotations

"""``python -m cclenzz`` entry point → ``cli.main()``."""

import sys

from .cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
