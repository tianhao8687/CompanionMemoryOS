from pathlib import Path

from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.romance import RomanceSettings, romantic_persona, romantic_rules


def test_private_remark_round_trip_restart_and_clear(tmp_path: Path) -> None:
    headers = {"X-Companion-Client": "local-web", "Origin": "http://127.0.0.1"}
    original = RomanceSettings(companion_name="知夏", model_mode="offline")
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", headers=headers) as client:
        client.get("/")
        values = original.model_dump(mode="json")
        values.update(companion_remark="  月亮  ", companion_note="  这份备注只留给自己看。  ")
        saved = client.put("/api/settings", json={"settings": values})
        assert saved.status_code == 200, saved.text

    with TestClient(
        create_app(tmp_path), base_url="http://127.0.0.1", headers=headers
    ) as restarted:
        restarted.get("/")
        settings = restarted.get("/api/bootstrap").json()["settings"]
        assert settings["companion_remark"] == "月亮"
        assert settings["companion_note"] == "这份备注只留给自己看。"
        assert settings["companion_name"] == "知夏"
        revised = RomanceSettings.model_validate(settings)
        assert romantic_persona(revised) == romantic_persona(original)
        assert romantic_rules(revised) == romantic_rules(original)
        # Reject overlong values without overwriting the saved private label.
        invalid = restarted.put(
            "/api/settings", json={"settings": {**settings, "companion_remark": "字" * 25}}
        )
        assert invalid.status_code == 422
        assert restarted.get("/api/bootstrap").json()["settings"]["companion_remark"] == "月亮"
        cleared = restarted.put(
            "/api/settings",
            json={"settings": {**settings, "companion_remark": " ", "companion_note": " "}},
        )
        assert cleared.status_code == 200, cleared.text

    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", headers=headers) as cleared:
        cleared.get("/")
        settings = cleared.get("/api/bootstrap").json()["settings"]
        assert settings["companion_remark"] == settings["companion_note"] == ""
        assert settings["companion_name"] == "知夏"
