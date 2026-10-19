"""Real public search + native playback integration in an owned guest emulator.

The unchanged AndroidMusicClient/MCP protocol runs on the host. The test-only
transport calls MusicBridge from the installed APK, avoiding old emulator ARM
translation failures. This does not assert Flutter or Chaquopy end-to-end playback.
NetEase must already be installed and its guest setup completed. No model calls.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from companion_agent.automation.models import MCPServerConfig
from companion_agent.integrations.netease_android import AndroidMusicClient

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"android-local-[a-f0-9]{32}", args.run_id):
        parser.error("Expected an owned Android test run ID")
    run = ROOT / ".agent-tests" / args.run_id
    report = {"scope": "host_mcp_to_installed_native_bridge", "model_calls": 0, "checks": []}

    def record(name: str, detail: object) -> None:
        report["checks"].append({"name": name, "status": "passed", "detail": detail})
        print(f"PASS {name}", flush=True)

    def bridge(name: str, arguments: dict) -> dict:
        raw = subprocess.check_output(
            [
                sys.executable,
                str(Path(__file__).with_name("probe_android_music.py")),
                "--adb",
                str(args.adb),
                "--run-id",
                args.run_id,
                "--request",
                json.dumps({"tool": name, "arguments": arguments}, ensure_ascii=False),
            ],
            timeout=120,
        )
        evidence = json.loads(raw)
        if report.get("apk_sha256") not in (None, evidence["apk_sha256"]):
            raise RuntimeError("Preview APK changed during the music test")
        report["apk_sha256"] = evidence["apk_sha256"]
        return evidence["result"]

    client = AndroidMusicClient(bridge)
    server = MCPServerConfig(id="netease", label="Guest test", transport="native", enabled=True)
    definitions = {tool["name"]: tool for tool in client.discover(server)}

    def call(name: str, **arguments: object) -> dict:
        result = client.call(server, name, arguments, definitions[name])["data"]
        if result.get("status") != "succeeded":
            raise AssertionError(result)
        return result

    def playing(title: str | None = None) -> dict:
        for _ in range(12):
            state = call("netease_playback_state")
            if state.get("playback") == "playing" and (title is None or state["title"] == title):
                return state
            time.sleep(1)
        raise AssertionError(f"No confirmed playing state: {state}")

    try:
        # This first native read independently verifies the active run ownership.
        status = call("netease_status")
        assert status["installed"] and status["media"]["permission"], status
        record("installed_player_and_media_permission", status)
        songs = call("netease_search_songs", query="茉莉花", limit=10)["songs"]
        song = next(
            s for s in songs if s["name"] == "茉莉花(江苏民歌)" and "中央民族乐团" in s["artists"]
        )
        record("real_mcp_public_song_search", {"selected": song, "result_count": len(songs)})
        receipt = json.loads((run / "results.json").read_text(encoding="utf-8"))
        # Same documented song URI as MusicBridge; shell delivery is explicitly
        # reported separately because Flutter cannot run on this older emulator.
        subprocess.run(
            [
                str(args.adb),
                "-s",
                receipt["serial"],
                "shell",
                "am",
                "start",
                "-W",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                f"orpheus://song/{song['id']}",
                "-p",
                "com.netease.cloudmusic",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        first = playing(song["name"])
        time.sleep(2)
        second = playing(song["name"])
        assert second["position_ms"] - first["position_ms"] >= 1500, (first, second)
        record("song_playing_and_progress_advancing", {"first": first, "second": second})
        paused = call("netease_control", action="pause")
        assert paused["verified"] and paused["state"]["playback"] == "paused", paused
        record("mcp_pause_readback", paused)
        resumed = call("netease_control", action="play")
        assert resumed["verified"] and resumed["state"]["playback"] == "playing", resumed
        record("mcp_resume_readback", resumed)
        changed = call("netease_control", action="next")
        assert changed["verified"] and changed["state"]["title"] != song["name"], changed
        next_state = playing(changed["state"]["title"])
        record("mcp_next_song_playing", next_state)
        previous = call("netease_control", action="previous")
        assert previous["verified"], previous
        restored = playing(song["name"])
        record("mcp_previous_song_playing", restored)
        seek = call(
            "netease_seek",
            position_ms=60000,
            **{k: restored[k] for k in ("title", "artist", "album")},
        )
        assert seek["verified"] and abs(seek["state"]["position_ms"] - 60000) <= 2000, seek
        record("mcp_seek_readback", seek)
        audio = subprocess.check_output(
            [str(args.adb), "-s", receipt["serial"], "shell", "dumpsys", "audio"], timeout=30
        ).decode("utf-8", "replace")
        package = (
            subprocess.check_output(
                [
                    str(args.adb),
                    "-s",
                    receipt["serial"],
                    "shell",
                    "pm",
                    "list",
                    "packages",
                    "-U",
                    "com.netease.cloudmusic",
                ],
                timeout=30,
            )
            .decode()
            .strip()
        )
        uid = package.split("uid:", 1)[1].strip()
        active = [
            line
            for line in audio.splitlines()
            if "AudioPlaybackConfiguration" in line
            and f"u/pid:{uid}/" in line
            and "state:started" in line
            and "USAGE_MEDIA" in line
        ]
        assert active, "NetEase has no active OS media audio track"
        (run / "audio-playback-final.txt").write_text(audio, encoding="utf-8")
        record("actual_android_audio_track_started", active)
        call("netease_control", action="pause")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=repr(error))
        raise
    finally:
        destination = run / f"music-mcp-{time.time_ns()}.json"
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(destination, flush=True)


if __name__ == "__main__":
    main()
