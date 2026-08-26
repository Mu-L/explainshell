import json
import logging
import sys

from explainshell.logger.json_logging import JsonFormatter


def _record(level: int, msg: str, *args, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="explainshell.web.views",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )


def test_format_basic() -> None:
    out = JsonFormatter().format(_record(logging.WARNING, "%r parsing error", "ls |"))
    entry = json.loads(out)
    assert entry["level"] == "warning"
    assert entry["logger"] == "explainshell.web.views"
    assert entry["message"] == "'ls |' parsing error"
    assert isinstance(entry["ts"], float)


def test_format_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        out = JsonFormatter().format(
            _record(logging.ERROR, "failed", exc_info=sys.exc_info())
        )
    entry = json.loads(out)
    assert entry["error"]["kind"] == "ValueError"
    assert entry["error"]["message"] == "boom"
    assert "ValueError: boom" in entry["error"]["stack"]


def test_single_line_output() -> None:
    try:
        raise ValueError("multi\nline")
    except ValueError:
        out = JsonFormatter().format(
            _record(logging.ERROR, "failed", exc_info=sys.exc_info())
        )
    assert "\n" not in out
