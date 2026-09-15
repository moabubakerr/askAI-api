"""``python -m askai.refresh``. The whole of the module is :mod:`askai.refresh.cli`."""

from __future__ import annotations

import sys

from askai.refresh.cli import main

if __name__ == "__main__":  # pragma: no cover -- exercised as a subprocess
    sys.exit(main())
