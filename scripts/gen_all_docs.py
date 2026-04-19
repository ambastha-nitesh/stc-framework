"""Master generator: regenerate every STC Framework Word document.

Idempotent. Run any time the underlying framework changes materially.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


HERE = Path(__file__).parent

GENERATORS = [
    "gen_framework_architecture.py",
    "gen_security_architecture.py",
    "gen_data_governance.py",
    "gen_cyber_defense.py",
    "gen_enterprise_architecture.py",
    "gen_prd.py",
    "gen_jira_spec.py",
    "gen_sdd.py",
]


def main() -> None:
    for g in GENERATORS:
        path = HERE / g
        if not path.exists():
            print(f"MISSING: {g}", file=sys.stderr)
            continue
        runpy.run_path(str(path), run_name="__main__")


if __name__ == "__main__":
    main()
