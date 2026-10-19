"""Emulator-only model recorder for real dot -> screen -> chat UI verification.

Loaded by the separately signed instrumentation APK, never imported by the app.
The controller, native reader, HTTP streaming, model preparation and database stay real.
Only language generation is replaced by a labelled, deterministic fixture.
"""

import builtins
import json
import time
from pathlib import Path

from companion_agent import local_runtime
from companion_agent.llm import ModelResponse, OpenAICompatibleMainLLM
from companion_agent.romance import SettingsUpdate

context = builtins._xinyu_smoke_context
run_id = builtins._xinyu_smoke_run
assert run_id.startswith("android-local-")
root = Path(str(context.getFilesDir().getAbsolutePath()))
report = root / ("screen-probe-" + run_id + ".json")
stop = root / ("screen-probe-" + run_id + ".stop")
calls = []
blocked_network_calls = []


def save():
    report.write_text(
        json.dumps(
            {"run_id": run_id, "calls": calls, "blocked_network_calls": blocked_network_calls},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def block_provider(*args, **kwargs):
    blocked_network_calls.append("provider_request_blocked")
    save()
    raise AssertionError("No provider/network calls are authorized in this synthetic run")


class RecordedModel:
    def generate(self, messages):
        calls.append([message.wire() for message in messages])
        save()
        return ModelResponse(
            text="【自动化测试回复】已收到当前页面，原对话同步正常。", model="screen-fixture"
        )


local_runtime.start_embedded(str(root / "xinyu-data"), context)
host = local_runtime._embedded.app.state.host
original = host.settings.model_copy(deep=True)
old_request = OpenAICompatibleMainLLM.request
try:
    OpenAICompatibleMainLLM.request = block_provider
    host.injected_llm = RecordedModel()
    host.save_settings(
        SettingsUpdate(
            settings=original.model_copy(
                update={
                    "storage_consent": True,
                    "model_consent": True,
                    "model_mode": "api",
                    "vision": "enabled",
                }
            )
        )
    )
    save()
    deadline = time.monotonic() + 1800
    while not stop.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
finally:
    host.injected_llm = None
    host.save_settings(SettingsUpdate(settings=original))
    OpenAICompatibleMainLLM.request = old_request
    save()
builtins._xinyu_smoke_result = json.dumps(
    {"calls": len(calls), "external_model_calls": 0, "blocked_network_calls": blocked_network_calls}
)
