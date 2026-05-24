#!/usr/bin/env python3
"""Generate a v3-format sample project repo — CLI shim.

The actual build logic lives in :mod:`siege.sample_project`. Keeping a
thin shim here so the historical ``python scripts/make_sample_project.py
<dest>`` invocation still works for hand-runs and for the integration
test fixture.

    python scripts/make_sample_project.py /tmp/siege-sample
    python -m siege.cli get-project-graph --repo /tmp/siege-sample
"""

from __future__ import annotations

import sys
from pathlib import Path

from siege.sample_project import build


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample-project").resolve()
    try:
        build(target)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"sample v3 project written to {target}")
    print(f"  inspect: python -m siege.cli get-project-graph --repo {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
