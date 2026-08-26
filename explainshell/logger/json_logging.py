"""JSON line logging for production.

Under gunicorn the app runs with no logging configured (runserver.py, which
sets up loguru, is the dev entrypoint only), so records fell through to
`logging.lastResort`, which prints the bare message with no level. Datadog
then ingested them as status=info plain text. Emitting one JSON object per
line fixes that: Datadog auto-parses JSON messages and maps `level` to the
log status and `message` to the message.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            # Datadog standard error attributes (error.kind/message/stack).
            entry["error"] = {
                "kind": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "stack": self.formatException(record.exc_info),
            }
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_json_logging(level: int = logging.WARNING) -> None:
    """Attach a JSON stderr handler to the root logger.

    Default WARNING matches lastResort's threshold — the matcher logs
    chattily at info (~10 lines per /explain), which was silently dropped
    before and would flood prod logs at INFO.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
