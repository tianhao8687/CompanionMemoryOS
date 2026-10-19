"""Refresh the pinned, unchanged in-process subset of droid-mcp (no network)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REVISION = "38723823a05852d3b2a655f48d817fc4bd3b406c"
CORE = (
    "McpTool.kt",
    "ToolParameter.kt",
    "ToolResult.kt",
    "ToolImage.kt",
    "ToolRegistry.kt",
    "ToolCallContext.kt",
    "ToolCallConfirmer.kt",
    "PermissionHelper.kt",
    "PermissionStatus.kt",
    "support/ModuleSupport.kt",
    "protocol/ToolSchemas.kt",
    "transport/InProcessTransport.kt",
)
MODULES = (
    "device",
    "screen",
    "settings",
    "apps",
    "alarms",
    "dnd",
    "vibration",
    "accessibility",
    "sensors",
)


def main() -> None:
    source = Path(sys.argv[1]).resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise SystemExit("Source must be droid-mcp v0.11.0 at the pinned revision")
    target = Path(__file__).resolve().parents[1] / "android" / "droid_mcp"
    files = [source / "LICENSE"]
    core = source / "droid-mcp-core/src/main/kotlin/io/droidmcp/core"
    files += [core / name for name in CORE]
    for module in MODULES:
        files += sorted((source / f"droid-mcp-{module}/src/main/kotlin").rglob("*.kt"))
    records = []
    for path in files:
        relative = path.relative_to(source).as_posix()
        destination = (
            target / "LICENSE"
            if path.name == "LICENSE"
            else target / "src/main/kotlin" / relative.split("/src/main/kotlin/", 1)[1]
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Read the Git blob, not a checkout transformed by Windows autocrlf.
        content = subprocess.check_output(
            ["git", "-C", str(source), "show", f"{REVISION}:{relative}"]
        )
        destination.write_bytes(content)
        records.append(
            {
                "source": relative,
                "path": destination.relative_to(target).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    (target / "UPSTREAM.json").write_text(
        json.dumps(
            {
                "repository": "https://github.com/stixez/droid-mcp",
                "version": "v0.11.0",
                "revision": revision,
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    license_asset = target.parents[1] / "assets/licenses/droid-mcp.txt"
    license_asset.parent.mkdir(parents=True, exist_ok=True)
    license_asset.write_bytes((target / "LICENSE").read_bytes())
    print(f"Copied {len(records)} unchanged upstream files at {revision}")


if __name__ == "__main__":
    main()
