from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import main

if __name__ == "__main__":
    raise SystemExit(
        main(run_mode="latest", apply_past_24h=True, sort_mode="latest")
    )