from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "payload", {}))
        return json.dumps(payload, default=str)


class EventLogger:
    def __init__(self, logger: logging.Logger, keep_records: bool = False):
        self._logger = logger
        self.records: Optional[List[Dict[str, Any]]] = [] if keep_records else None

    def event(self, name: str, level: str = "info", **fields: Any) -> None:
        if self.records is not None:
            self.records.append({"event": name, "level": level, **fields})
        getattr(self._logger, level)(name, extra={"payload": fields})

    def error(self, name: str, **fields: Any) -> None:
        self.event(name, level="error", **fields)

    def names(self) -> List[str]:
        return [r["event"] for r in (self.records or [])]


def get_event_logger(
    name: str = "algodesk",
    log_dir: Optional[str] = None,
    console: bool = False,
    level: int = logging.INFO,
    keep_records: bool = False,
) -> EventLogger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if not getattr(logger, "_algodesk_ready", False):
        formatter = JsonFormatter()
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(log_dir, f"{name}.jsonl"), encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        if console:
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            logger.addHandler(ch)
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        logger._algodesk_ready = True
    return EventLogger(logger, keep_records=keep_records)