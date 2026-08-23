import argparse
import json
from pathlib import Path

from app.main import app


def canonical_schema() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="openapi.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    generated = canonical_schema()

    if args.check:
        if not output.exists():
            raise SystemExit(f"missing committed OpenAPI contract: {output}")
        if output.read_text(encoding="utf-8") != generated:
            raise SystemExit("OpenAPI drift detected; regenerate and commit openapi.json")
        return 0

    output.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
