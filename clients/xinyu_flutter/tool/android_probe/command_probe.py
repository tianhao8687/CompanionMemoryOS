"""Explicit tool requests in a signed, emulator-only instrumentation process.

Uses the installed app's clients and real Android bridge. No model or private
account data access. Public music requests are enabled only by this test driver.
"""

import builtins
import json
import time

from companion_agent.automation.models import MCPServerConfig
from companion_agent.integrations.droid_android import android_phone_client
from companion_agent.integrations.netease_android import android_client

request = json.loads(builtins._xinyu_smoke_request)
context = builtins._xinyu_smoke_context
if request.get("server", "netease") == "netease":
    client = android_client(context)
    server = MCPServerConfig(id="netease", label="Music test", transport="native", enabled=True)
else:
    client = android_phone_client(context)
    server = client.template()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not client.state()["permissions"]["accessibility"]:
        time.sleep(0.2)
catalog = client.discover(server)
definition = next(tool for tool in catalog if tool["name"] == request["tool"])
result = client.call(server, definition["name"], request.get("arguments", {}), definition)
builtins._xinyu_smoke_result = json.dumps(result, ensure_ascii=False)
