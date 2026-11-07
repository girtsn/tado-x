"""Read bundled integration version for automatic frontend cache busting."""

from __future__ import annotations

import json
from pathlib import Path

INTEGRATION_VERSION: str = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)["version"]
