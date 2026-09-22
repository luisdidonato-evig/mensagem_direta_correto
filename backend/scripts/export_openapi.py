"""Regenerate contracts/openapi.json from the current FastAPI app.

Usage: python scripts/export_openapi.py   (run from backend/)
"""

import json
from pathlib import Path

from app.main import app

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "openapi.json"


def main() -> None:
    OUTPUT_PATH.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OpenAPI snapshot written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
