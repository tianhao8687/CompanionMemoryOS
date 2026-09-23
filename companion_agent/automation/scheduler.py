from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any
from zoneinfo import ZoneInfo

from companion_agent.automation.models import ScheduleInput
from companion_agent.automation.store import AutomationStore, utc_now


class Scheduler:
    def __init__(self, store: AutomationStore) -> None:
        self.store = store
        self.dispatch: Callable[[dict[str, Any], str], dict[str, Any]] | None = None
        self.enabled: Callable[[], bool] = lambda: True
        self.on_tick: Callable[[], None] | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    def create(self, item: ScheduleInput, key: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        if item.at <= now:
            raise ValueError("请填写未来的时间。")
        if len(json.dumps(item.arguments)) > 12000:
            raise ValueError("任务参数过长。")
        job_id = hashlib.sha256(key.encode()).hexdigest()[:32]
        with self.store.database.atomic() as db:
            prior = db.execute("SELECT * FROM agent_jobs WHERE id=?", (job_id,)).fetchone()
            if prior is not None:
                return {"status": "succeeded", "job_id": job_id, "reused": True}
            count = db.execute(
                "SELECT count(*) FROM agent_jobs WHERE status IN ('active','paused','running')"
            ).fetchone()[0]
            if count >= 200:
                raise ValueError("任务数量已达上限，请先取消不需要的任务。")
            db.execute(
                "INSERT INTO agent_jobs VALUES (?, ?, ?, 'active', '', ?)",
                (
                    job_id,
                    item.model_dump_json(),
                    item.at.astimezone(UTC).isoformat(),
                    utc_now(),
                ),
            )
        return {
            "status": "succeeded",
            "job_id": job_id,
            "at": item.at.isoformat(),
            "repeat": item.repeat,
            "message": "任务已保存；本地服务运行时触发。",
        }

    def change(self, job_id: str, status: str) -> None:
        if status not in {"active", "paused", "cancelled"}:
            raise ValueError("invalid job status")
        with self.store.database.atomic() as db:
            row = db.execute("SELECT status FROM agent_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["status"] in {"running", "completed", "cancelled"}:
                raise ValueError("任务不存在或已结束 / 正在执行。")
            db.execute("UPDATE agent_jobs SET status=? WHERE id=?", (status, job_id))

    @staticmethod
    def next_time(item: ScheduleInput, due: datetime, now: datetime) -> datetime | None:
        if item.repeat == "once":
            return None
        if item.repeat == "interval":
            period = timedelta(minutes=item.interval_minutes or 1)
            return due + period * (max(0, (now - due) // period) + 1)
        zone = ZoneInfo(item.timezone)
        local = now.astimezone(zone)
        clock = item.at.astimezone(zone)
        result = local.replace(
            hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=clock.microsecond
        )
        if result <= local:
            result += timedelta(days=1)
        return result.astimezone(UTC)

    def tick(self, now: datetime | None = None) -> None:
        if not self.enabled():
            return
        now = now or datetime.now(UTC)
        # Claims are transactional. Missed recurring runs coalesce into one run.
        with self.store.database.atomic() as db:
            rows = db.execute(
                "SELECT * FROM agent_jobs WHERE status='active' AND next_run<=? "
                "ORDER BY next_run LIMIT 10",
                (now.isoformat(),),
            ).fetchall()
            for row in rows:
                db.execute("UPDATE agent_jobs SET status='running' WHERE id=?", (row["id"],))
        for row in rows:
            item = ScheduleInput.model_validate_json(row["data"])
            try:
                if item.tool_name:
                    if self.dispatch is None:
                        raise ValueError("no tool dispatcher")
                    result = self.dispatch(dict(row), f"job:{row['id']}:{row['next_run']}")
                else:
                    self.store.notification(item.conversation_id, item.title, item.message)
                    result = {"status": "succeeded", "message": "提醒已送达应用内通知。"}
            except Exception:
                result = {"status": "uncertain", "message": "执行未完成，已暂停，请核对结果。"}
            next_run = self.next_time(item, datetime.fromisoformat(row["next_run"]), now)
            status = "active" if next_run else "completed"
            if result.get("status") != "succeeded":
                status = "paused"
                self.store.notification(
                    item.conversation_id,
                    item.title,
                    "定时操作需要处理，已暂停。请打开能力与定时查看。",
                )
            with self.store.database.connection() as db:
                db.execute(
                    "UPDATE agent_jobs SET status=?, next_run=?, last_result=? WHERE id=?",
                    (
                        status,
                        (next_run or now).isoformat(),
                        json.dumps(result, ensure_ascii=False),
                        row["id"],
                    ),
                )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.recover()
        self._stop.clear()
        self._thread = Thread(target=self._run, name="companion-scheduler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
                if self.on_tick:
                    self.on_tick()
            except Exception:
                # Keep the scheduler alive without leaking remote exception data.
                import logging

                logging.getLogger(__name__).warning("scheduler_tick_failed")
            self._stop.wait(1)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
