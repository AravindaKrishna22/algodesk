from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional


class StateStoreError(Exception):
    pass


class JSONStateStore:
    def __init__(self, path: str):
        self.path = path
        self.backup_path = path + ".bak"
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)

    def exists(self) -> bool:
        return os.path.exists(self.path) or os.path.exists(self.backup_path)

    def save(self, data: Dict[str, Any]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
            
        # Windows can temporarily lock files (OneDrive, Antivirus). Retry a few times.
        for attempt in range(5):
            try:
                if os.path.exists(self.path):
                    # Remove old backup if it exists to prevent overwrite errors
                    if os.path.exists(self.backup_path):
                        try:
                            os.remove(self.backup_path)
                        except OSError:
                            pass
                    os.replace(self.path, self.backup_path)
                os.replace(tmp, self.path)
                break  # Success
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)

    def _read(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            data = self._read(self.path)
            if data is not None:
                return data
        except (json.JSONDecodeError, OSError):
            pass
        try:
            return self._read(self.backup_path)
        except (json.JSONDecodeError, OSError) as exc:
            raise StateStoreError(f"state file and backup are unreadable: {exc}")

    def clear(self) -> None:
        for p in (self.path, self.backup_path, self.path + ".tmp"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass