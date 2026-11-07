"""Integration version from bundled manifest for frontend cache invalidation."""
import json
from pathlib import Path

INTEGRATION_VERSION = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)["version"]
