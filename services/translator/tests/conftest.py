"""Pytest bootstrap for the translator service tests.

Adds ``services/translator/`` and the repo root to ``sys.path`` so
``app.*`` and ``shared.*`` imports resolve when pytest is run from any cwd.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SERVICE_ROOT = _HERE.parents[1]  # services/translator/
_REPO_ROOT = _SERVICE_ROOT.parents[1]  # repo root

for p in (_REPO_ROOT, _SERVICE_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
