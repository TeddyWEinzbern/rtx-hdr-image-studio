"""Private subprocess entry point. Never invoked through a shell."""

import json
import sys
import traceback
from pathlib import Path

from .pipeline import EVENT_PREFIX, process_files


def emit(event: dict) -> None:
    print(EVENT_PREFIX + json.dumps(event), flush=True)


def main() -> int:
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        results = process_files(request, emit)
        emit({"event": "finished", "results": results})
        return 0
    except Exception as error:
        traceback.print_exc()
        emit({"event": "error", "message": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
