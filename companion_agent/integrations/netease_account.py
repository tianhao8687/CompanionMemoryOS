"""Read only the Windows client's current public account identity, never login secrets."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


def current_account(database: Path | None = None) -> dict[str, Any]:
    if database is None:
        root = os.environ.get("LOCALAPPDATA")
        if sys.platform != "win32" or not root:
            return {"status": "failed", "message": "当前设备无法读取电脑版网易云账号。"}
        database = Path(root) / "Netease/CloudMusic/Library/webdb.dat"
    try:
        # A single, known metadata row. Do not scan account files, request caches,
        # cookies, old users, playing-count tables or encrypted localdata.
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
            db.execute("PRAGMA query_only=ON")
            db.set_progress_handler(lambda: 1, 100_000)
            row = db.execute(
                "SELECT jsonStr FROM persistentModel WHERE uniKey='host' "
                "AND length(jsonStr) BETWEEN 1 AND 65536 LIMIT 1"
            ).fetchone()
        value = json.loads(row[0]).get("data", {}) if row else {}
        identifier = str(value.get("uid", ""))
        if value.get("isAnonymous") is False and re.fullmatch(r"[1-9][0-9]{0,17}", identifier):
            return {
                "status": "succeeded",
                "available": True,
                "user_id": identifier,
                "source": "windows_current_account",
                "message": "已识别此设备网易云当前账号，可直接读取可访问的歌单。",
            }
    except (OSError, sqlite3.Error, ValueError, AttributeError, TypeError):
        pass
    return {
        "status": "succeeded",
        "available": False,
        "needs_login": True,
        "platform": "windows",
        "message": "暂未识别当前账号，请先在电脑版网易云登录；无需复制歌单链接。",
    }
