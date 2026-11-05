"""Start the judge result consumer with .env loaded."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.env_loader import load_env  # noqa: E402

load_env()

from app.tasks.consumer import consume_results  # noqa: E402

if __name__ == "__main__":
    consume_results()
