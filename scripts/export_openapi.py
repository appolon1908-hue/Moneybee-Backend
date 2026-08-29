import json
from pathlib import Path

from app.main import app


target = Path("openapi.json")
target.write_text(
    json.dumps(app.openapi(), sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
