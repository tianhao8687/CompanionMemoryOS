"""Phone companion controls through HTTP and chat; synthetic device/clock only."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.integrations.droid_android import AndroidPhoneClient
from companion_agent.phone_comfort import RESTORE, TOOL
from tests.test_phone_comfort import adjust, chat, receipt
from tests.test_phone_comfort import companion as companion
from tests.test_romance_app import HEADERS

CONTROL = "/api/automation/phone-comfort/control"


def control(client, action, action_ids=None):
    return client.post(CONTROL, json={"action": action, "action_ids": action_ids or []})


def keep(client):
    rows = client.get("/api/automation").json()["phone_comfort"]["active"]
    return control(client, "keep", list({r["action_id"] for r in rows}))


def set_clock(monkeypatch, instant):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr("companion_agent.phone_comfort.datetime", Clock)


@pytest.mark.parametrize("minutes", [1, 3, 5])
def test_interval_boundary_and_skipped_retry_does_not_extend_it(companion, monkeypatch, minutes):
    client, host, phone, _, _ = companion
    config = client.get("/api/automation").json()["config"]
    config["phone_comfort"]["cooldown_minutes"] = minutes
    assert client.put("/api/automation/config", json=config).status_code == 200
    chat(companion, "我好累啊", adjust("我好累啊"))
    action = next(a for a in host.tools.store.actions() if a["tool_name"] == TOOL)
    finished = datetime.fromisoformat(action["updated_at"])
    assert keep(client).status_code == 200
    set_clock(monkeypatch, finished + timedelta(minutes=minutes, milliseconds=-1))
    chat(companion, "我还是好累啊", adjust("我还是好累啊"), "too-soon")
    assert receipt(host)["reason"] == "cooldown" and len(phone.writes) == 1
    set_clock(monkeypatch, finished + timedelta(minutes=minutes, milliseconds=1))
    chat(companion, "我眼睛还是好酸", adjust("我眼睛还是好酸"), "after-interval")
    assert receipt(host)["verified"] and len(phone.writes) == 2


@pytest.mark.parametrize("value", [0, 6, True, 1.5, "1"])
def test_interval_rejects_invalid_values_without_changing_consent(companion, value):
    client, host, _, _, _ = companion
    config = client.get("/api/automation").json()["config"]
    config["phone_comfort"]["cooldown_minutes"] = value
    assert client.put("/api/automation/config", json=config).status_code == 422
    assert host.tools.config.phone_comfort.cooldown_minutes == 3
    assert host.tools.config.phone_comfort.enabled


def test_legacy_config_defaults_to_three_minutes_and_preserves_permissions(companion):
    client, _, _, _, _ = companion
    config = client.get("/api/automation").json()["config"]
    config["phone_comfort"].pop("cooldown_minutes")
    config["phone_comfort"].pop("paused_until")
    assert client.put("/api/automation/config", json=config).status_code == 200
    saved = client.get("/api/automation").json()["config"]
    assert saved["phone_comfort"]["cooldown_minutes"] == 3
    assert saved["servers"] == config["servers"]


def test_pending_adjustment_blocks_stacking_after_interval(companion, monkeypatch):
    _, _, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊"))
    set_clock(monkeypatch, datetime.now(UTC) + timedelta(minutes=10))
    chat(companion, "我还是好累啊", adjust("我还是好累啊"), "later")
    assert len(phone.writes) == 1


def test_keep_preserves_device_and_cooldown_without_more_reads_or_writes(companion):
    client, host, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊", ["screen", "media"]))
    reads = list(phone.reads)
    assert keep(client).status_code == 200
    assert not host.phone_comfort.active()
    assert len(phone.writes) == 2 and phone.reads == reads
    assert client.post("/api/automation/phone-comfort/restore").json()["verified"]
    assert phone.settings["screen_brightness"] == 120
    assert phone.settings["volume_media"] == 6
    chat(companion, "我还是好累啊", adjust("我还是好累啊"), "after-keep")
    assert receipt(host)["reason"] == "cooldown" and len(phone.writes) == 2


@pytest.mark.parametrize("case", ["stale", "uncertain"])
def test_keep_cannot_discard_new_or_unconfirmed_recovery_records(companion, case):
    client, host, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊"))
    ids = [host.phone_comfort.active()[0]["action_id"]]
    if case == "stale":
        ids = ["old-action"]
    else:
        with host.database.connection() as db:
            db.execute("UPDATE phone_comfort_changes SET status='uncertain'")
    assert control(client, "keep", ids).status_code == 409
    assert host.phone_comfort.active() and len(phone.writes) == 1


def test_pause_blocks_adjustment_and_automatic_restore_but_allows_explicit_restore(companion):
    client, host, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊"))
    rules = host.tools.config.model_dump(mode="json")["servers"]
    assert control(client, "pause").status_code == 200
    until = host.tools.config.phone_comfort.paused_until
    assert timedelta(minutes=14) < until - datetime.now(UTC) <= timedelta(minutes=15)
    assert client.get("/api/automation").json()["phone_comfort"]["paused"]
    assert "用户已暂停主动手机调整" in host.phone_comfort.context()
    reads = list(phone.reads)
    chat(companion, "我缓过来了", [(RESTORE, {"evidence": "我缓过来了"})], "auto-restore")
    chat(companion, "我还是好累啊", adjust("我还是好累啊"), "while-paused")
    assert phone.reads == reads and len(phone.writes) == 1
    chat(companion, "请恢复手机设置", [(RESTORE, {"evidence": "恢复手机设置"})], "explicit-restore")
    assert phone.settings["screen_brightness"] == 160 and not host.phone_comfort.active()
    assert host.tools.config.model_dump(mode="json")["servers"] == rules
    assert host.phone_comfort.paused()


def test_pause_restart_expiry_does_nothing_until_next_chat(companion, tmp_path, monkeypatch):
    client, host, phone, model, conversation = companion
    assert control(client, "pause").status_code == 200
    until = host.tools.config.phone_comfort.paused_until
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_phone=AndroidPhoneClient(phone),
    )
    restarted = app.state.host
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as other:
        other.get("/")
        assert restarted.phone_comfort.paused()
        assert restarted.tools.config.phone_comfort.paused_until == until
        set_clock(monkeypatch, until + timedelta(seconds=1))
        assert not other.get("/api/automation").json()["phone_comfort"]["paused"]
        assert not phone.reads and not phone.writes
        chat((other, restarted, phone, model, conversation), "我好累啊", adjust("我好累啊"))
        assert len(phone.writes) == 1


def test_resume_preserves_optout_and_cooldown(companion):
    client, host, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊"))
    assert control(client, "pause").status_code == 200
    assert client.post("/api/automation/phone-comfort/restore").json()["verified"]
    assert control(client, "resume").status_code == 200
    assert host.tools.config.phone_comfort.paused_until is None
    chat(companion, "我还是好累啊", adjust("我还是好累啊"), "after-resume")
    assert receipt(host)["reason"] == "cooldown"
    assert control(client, "pause").status_code == 200
    chat(companion, "别替我调整了", [], "opt-out")
    assert control(client, "resume").status_code == 200
    assert not host.tools.config.phone_comfort.enabled
    assert len(phone.writes) == 2


def test_pause_input_requires_timezone_and_control_requires_same_origin(companion):
    client, host, _, _, _ = companion
    config = client.get("/api/automation").json()["config"]
    config["phone_comfort"]["paused_until"] = "2026-10-19T12:00:00"
    assert client.put("/api/automation/config", json=config).status_code == 422
    assert (
        client.post(
            CONTROL, json={"action": "pause"}, headers={"Origin": "https://example.com"}
        ).status_code
        == 403
    )
    assert not host.phone_comfort.paused()
    assert control(client, "unknown").status_code == 422
