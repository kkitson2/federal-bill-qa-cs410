"""Export the current collection using local pg_dump; Docker is not required."""

import json
from pathlib import Path

from dotenv import load_dotenv

from billbridge_data.handoff import export_database

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env", override=False)
    print(json.dumps(export_database(ROOT / "data", ROOT / "database"), indent=2))


if __name__ == "__main__":
    main()
