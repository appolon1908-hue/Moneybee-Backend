import json
from pathlib import Path

from app.main import app

Path("openapi.json").write_text(
    json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
