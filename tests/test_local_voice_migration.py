"""Old voice settings cannot restore the removed commercial ASR integration."""

import pytest

from companion_agent.app import create_app
from companion_agent.romance import RomanceSettings


@pytest.mark.parametrize("provider", ["doubao", "system", "local"])
def test_old_provider_is_discarded_without_losing_other_settings(provider):
    settings = RomanceSettings.model_validate(
        {"voice_provider": provider, "companion_name": "小禾", "font_size": "large"}
    )
    assert "voice_provider" not in settings.model_dump()
    assert settings.companion_name == "小禾"
    assert settings.font_size == "large"


def test_cloud_voice_routes_are_not_installed(tmp_path):
    # Route inspection, no microphone or network service invocation.
    app = create_app(data_dir=tmp_path)
    assert not any(getattr(route, "path", "").startswith("/api/voice/") for route in app.routes)
