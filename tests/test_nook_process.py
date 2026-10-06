"""Real process + loopback HTTP artist. No external model requests or credentials."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from companion_agent.deepseek import DeepSeekConfig
from companion_agent.romance import RomanceSettings
from companion_agent.testing.driver import ManagedInstance
from tests.test_memory_nook import pixels, visual_brief
from tests.test_nook_drawing import material_drawing


def test_nook_real_process_and_optional_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    fixture_art = material_drawing()
    fixture_art["layers"][-1]["ops"] = [["grid", 40, 43, ["1"]]]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            if "像素艺术家" in body["messages"][0]["content"]:
                data = json.loads(body["messages"][-1]["content"])
                text = json.dumps(
                    {"art": fixture_art}
                    if "brief" in data
                    else {
                        "object": {
                            "title": "咖啡小火箭",
                            "meaning": "由咖啡小火箭这个比喻想到的小灯。",
                            "sources": [data["sources"][0]["ref"]],
                            "reality_layer": "real_world",
                            "zone": "desk",
                            "slot": 0,
                            "brief": visual_brief(),
                            "update_id": None,
                        }
                    },
                    ensure_ascii=False,
                )[:-1]  # A complete drawing with only the outermost brace missing.
            else:
                text = "合成模型回复：这只咖啡小火箭有自己的名字了。"
            payload = {
                "model": "local-pixel-fixture",
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("DEEPSEEK_BASE_URL", endpoint)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-local-fixture-key")
    settings = RomanceSettings(
        storage_consent=True,
        model_consent=True,
        model_mode="api",
        deepseek=DeepSeekConfig(base_url=endpoint, model="deepseek-chat"),
    )
    settings.cognition.model_extraction = False
    channel = os.environ.get("COMPANION_TEST_BROWSER_CHANNEL")
    instance = ManagedInstance(
        Path(".agent-tests"),
        allow_live=True,
        max_turns=4,
        max_calls=8,
        max_output_tokens=4096,
        timeout=180,
        settings=settings.model_dump(mode="json"),
    )
    evidence: dict[str, Any] = {
        "status": "failed",
        "level": "real-process-loopback-model-fixture",
        "artistic_quality": "not_reviewed",
    }
    try:
        client = instance.start()
        conversation = client.new_session()
        response = client.send_message(conversation, "我把自己叫作靠咖啡续航的小火箭。")
        moment = client.request(
            "POST",
            "/api/journal/moments",
            {
                "request_id": "nook-fixture-memory",
                "conversation_id": conversation,
                "title": "咖啡小火箭",
                "content": "我给自己起了咖啡小火箭这个名字。",
                "happened_on": date.today().isoformat(),
                "source_ids": [response["user"]["id"]],
            },
        )
        client.request("PUT", "/api/nook/settings", {"enabled": True, "daily_limit": 2})
        if channel:
            evidence["browser"] = browser_controls(instance, conversation, channel)
        else:
            assert (
                client.request("POST", "/api/nook/create", {"conversation_id": conversation})[
                    "status"
                ]
                == "drawing"
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            room = client.request("GET", "/api/nook")
            if not room["busy"]:
                break
            time.sleep(0.05)
        assert room["status"] == "created" and len(room["items"]) == 1
        assert client.connect()["accounting"]["calls"] == len(calls) == 3
        item = room["items"][0]
        assert room["pixel_side"] == len(item["art"]["rows"]) == 48
        assert item["art"]["rows"][43][40] == "1"
        client = instance.restart()
        assert client.request("GET", "/api/nook")["items"][0] == item
        client.request("POST", f"/api/memories/{moment['id']}/forget", {})
        assert client.request("GET", "/api/nook")["items"] == []
        assert client.request("GET", "/api/nook")["timeline"] == []
        evidence.update(
            status="passed",
            identity=client.connect(),
            calls=len(calls),
            restart="passed",
            source_forgetting="passed",
        )
    finally:
        instance.stop()
        server.shutdown()
        server.server_close()
        server_thread.join(5)
        (instance.directory / "nook-results.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"nook_run_id={instance.run_id}")


def browser_controls(instance: ManagedInstance, conversation: str, channel: str) -> dict[str, Any]:
    from playwright.sync_api import expect, sync_playwright

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 1000}, locale="zh-CN")
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(instance.client.url)
            page.locator("#open-nook").click()
            expect(page.locator("#nook-dialog")).to_be_visible()
            expect(page.locator("#nook-enabled")).to_be_checked()
            expect(page.locator("#nook-room")).to_have_attribute("data-ready", "true")
            expect(page.locator("#nook-detail")).to_be_hidden()
            page.locator("#nook-room").screenshot(
                path=str(instance.directory / "nook-empty-room.png")
            )
            for zone, label in [
                ("window", "窗台"),
                ("shelf", "纪念架"),
                ("wall", "回忆墙"),
                ("floor", "地毯"),
            ]:
                page.get_by_role("button", name=f"靠近{label}", exact=True).click()
                expect(page.locator("#nook-room")).to_have_attribute("data-view", zone)
                page.get_by_role("button", name="返回全景", exact=True).click()
                expect(page.locator("#nook-room")).to_have_attribute("data-view", "all")
            page.locator("#nook-create").click()
            expect(page.locator("#nook-items button")).to_have_count(1, timeout=20000)
            assert page.locator("#nook-items canvas").evaluate(
                "el => el.width === 48 && el.height === 48 && "
                "el.getContext('2d').getImageData(40, 43, 1, 1).data[3] === 255"
            )  # The former 32px canvas clipped this real model-path fixture pixel.
            # Select the tabletop in the full room, then the visible fixture pixel
            # in the close view. This catches incorrect inverse-camera hit testing.
            surface = page.locator("#nook-room")
            bounds = surface.bounding_box()
            assert bounds is not None
            surface.click(position={"x": bounds["width"] * 0.26, "y": bounds["height"] * 0.54})
            expect(surface).to_have_attribute("data-view", "desk")
            surface.screenshot(path=str(instance.directory / "nook-desk.png"))
            bounds = surface.bounding_box()
            assert bounds is not None
            surface.click(
                position={"x": bounds["width"] * 0.25, "y": bounds["height"] * (174 / 420)}
            )
            expect(page.locator("#nook-detail")).to_contain_text("咖啡小火箭")
            expect(page.locator(".nook-closeup")).to_be_visible()
            page.locator("#nook-detail").screenshot(
                path=str(instance.directory / "nook-closeup.png")
            )
            page.get_by_text("看看创作来源", exact=True).click()
            expect(page.locator("#nook-detail blockquote").first).to_contain_text("小火箭")
            page.get_by_role("button", name="收进收纳盒", exact=True).click()
            expect(page.locator("#nook-stored-count")).to_have_text("1")
            page.locator(".nook-drawer summary").click()
            page.locator("#nook-stored button").click()
            page.get_by_role("button", name="摆回小窝", exact=True).click()
            expect(page.locator("#nook-items button")).to_have_count(1)
            page.get_by_role("button", name="回到小窝", exact=True).click()
            expect(page.locator("#nook-detail")).to_be_hidden()
            expect(surface).to_have_attribute("data-view", "all")
            page.locator("#nook-room").screenshot(path=str(instance.directory / "nook-pixels.png"))
            for width in (736, 390, 320):
                page.set_viewport_size({"width": width, "height": 980})
                assert page.locator("#nook-dialog").evaluate(
                    "el => el.scrollWidth <= el.clientWidth + 1"
                )
                page.locator("#nook-dialog").evaluate("el => el.scrollTop = 0")
                page.screenshot(path=str(instance.directory / f"nook-{width}.png"))
            # Separate UI-only positioning fixture. It does not create memories or
            # model art, and is removed before the real-process lifecycle checks.
            positioning = instance.client.request("GET", "/api/nook")
            item = positioning["items"][0]
            positioning["items"] = [
                {
                    **item,
                    "id": f"layout-{zone}-{slot}",
                    "title": f"定位标记 {zone} {slot}",
                    "zone": zone,
                    "slot": slot,
                    "art": {**pixels(), "palette": ["#79604B", "#DBA78C"]},
                }
                for zone in ("window", "shelf", "desk", "wall", "floor")
                for slot in range(3)
            ]
            page.route("**/api/nook", lambda route: route.fulfill(json=positioning))
            page.get_by_role("button", name="刷新小窝", exact=True).click()
            expect(page.locator("#nook-items button")).to_have_count(15)
            page.set_viewport_size({"width": 1100, "height": 1100})
            surface.screenshot(path=str(instance.directory / "nook-all-slots-fixture.png"))
            for label in ("窗台", "纪念架", "回忆墙"):
                page.get_by_role("button", name=f"靠近{label}", exact=True).click()
                surface.screenshot(path=str(instance.directory / f"nook-slots-{label}.png"))
            page.unroute("**/api/nook")
            page.get_by_role("button", name="刷新小窝", exact=True).click()
            expect(page.locator("#nook-items button")).to_have_count(1)
            assert not errors
            return {
                "status": "passed",
                "widths": [736, 390, 320],
                "errors": errors,
                "conversation": conversation,
                "region_zoom": "passed",
                "zoomed_sprite_hit": "passed",
                "closeup_and_return": "passed",
            }
        except Exception:
            page.screenshot(path=str(instance.directory / "nook-failure.png"))
            raise
        finally:
            browser.close()
