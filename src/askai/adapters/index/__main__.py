"""``python -m askai.adapters.index`` -- the retrieval quality harness (AD-30).

``SystemExit`` is raised rather than ``sys.exit`` called, because everything in this
package is held to the standard library plus this project and reaches for as little of
either as it can (NFR-4); the exit code is the same one.
"""

from __future__ import annotations

from askai.adapters.index.quality import main

if __name__ == "__main__":
    raise SystemExit(main())
