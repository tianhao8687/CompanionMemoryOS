"""Exercise both entrances and one shared clock in an isolated, real browser process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from companion_agent.testing.driver import ManagedInstance


def smoke(instance: ManagedInstance, *, channel: str | None) -> dict[str, Any]:
    from playwright.sync_api import expect, sync_playwright

    client = instance.client
    errors: list[str] = []
    screenshots: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=channel)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            reduced_motion="reduce",
            locale="zh-CN",
        )
        context.on("page", lambda p: p.on("pageerror", lambda e: errors.append(str(e))))
        page = context.new_page()

        def capture(name: str) -> None:
            page.screenshot(
                path=str(instance.directory / name), full_page=True, animations="disabled"
            )
            screenshots.append(name)

        def snapshot() -> dict[str, Any]:
            result: dict[str, Any] = client.request("GET", "/api/focus")
            return result

        try:
            page.goto(client.url)
            page.wait_for_function("() => Boolean(state.config && state.active)")
            page.locator("#open-focus").click()
            expect(page.locator("#focus-setup-dialog")).to_be_visible()
            expect(page.locator("#focus-minutes")).to_have_value("30")
            expect(page.locator("#focus-intention")).to_have_value("")
            expect(page.locator("#focus-setup-dialog [data-focus-ambient]")).to_have_value("silent")
            expect(page.locator("#focus-setup-dialog [data-focus-notice-status]")).to_contain_text(
                "提示"
            )
            capture("focus-confirm-desktop.png")
            page.keyboard.press("Escape")
            expect(page.locator("#open-focus")).to_be_focused()
            page.locator("#open-nook").click()
            expect(page.locator("#nook-dialog")).to_be_visible()
            expect(page.locator("#focus-desk-entry")).to_be_visible()
            page.locator("#focus-desk-entry").click()
            expect(page.locator("#focus-setup-dialog")).to_be_visible()
            assert snapshot()["session"] is None
            page.keyboard.press("Escape")
            page.locator('[data-close="nook-dialog"]').click()

            page.locator("#message-input").fill("我得把商品资料整理一下，你陪我半小时。")
            page.locator("#send-message").click()
            expect(page.locator(".focus-card")).to_be_visible()
            expect(page.locator(".focus-card input").first).to_have_value("整理商品资料")
            expect(page.locator(".focus-card input").nth(1)).to_have_value("30")
            assert snapshot()["session"] is None
            capture("focus-chat-card.png")
            page.locator(".focus-card input").nth(1).fill("1")
            page.locator(".focus-card button").click()
            expect(page.locator("#focus-mini")).to_be_visible()
            active = snapshot()["session"]
            assert active["focus_minutes"] == 1
            page.locator("#focus-mini-open").click()
            expect(page.locator("#focus-stage")).to_have_text("专注中")
            expect(page.locator("#focus-current-task")).to_have_text("整理商品资料")
            page.wait_for_function(
                "() => document.querySelector('#nook-room').dataset.ready === 'true'"
            )
            for width, height in [(1440, 1000), (1024, 900), (768, 1024), (320, 740)]:
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                    f"page overflow at {width}"
                )
                assert page.locator("#nook-dialog").evaluate(
                    "e => e.clientWidth <= innerWidth && e.clientHeight <= innerHeight"
                )
                assert page.locator(".nook-body").evaluate(
                    "e => e.scrollWidth <= e.clientWidth + 1"
                ), f"room overflow at {width}"
                capture(f"focus-room-{width}.png")
            page.set_viewport_size({"width": 1440, "height": 1000})
            with page.expect_popup() as popup:
                page.locator("#focus-popout").click()
            mini = popup.value
            expect(mini.locator("#phase")).to_have_text("专注中")
            mini.locator("#pause").click()
            expect(page.locator("#focus-stage")).to_have_text("已暂停", timeout=10000)
            paused = snapshot()["session"]
            assert paused["id"] == active["id"]
            mini.close()
            page.reload()
            page.wait_for_function("() => Boolean(state.config && state.active)")
            page.locator("#open-nook").click()
            expect(page.locator("#focus-stage")).to_have_text("已暂停")
            assert snapshot()["session"]["remaining_seconds"] == paused["remaining_seconds"]
            page.locator("#focus-primary-action").click()
            expect(page.locator("#focus-stage")).to_have_text("专注中")
            page.locator("#focus-options summary").click()
            page.locator("#nook-dialog [data-focus-ambient]").select_option("rain")
            page.wait_for_function("() => focusAudio.playing()")
            assert snapshot()["preferences"]["focus_sound"] == "rain"
            page.locator("#nook-dialog [data-focus-ambient]").select_option("silent")
            page.wait_for_function("() => !focusAudio.playing()")
            page.locator("#focus-options summary").click()
            print("Focus acceptance: waiting for the real one-minute deadline.", flush=True)
            expect(page.locator("#focus-stage")).to_have_text("时间到了", timeout=65000)
            expect(page.locator("#focus-note")).to_have_text("1 分钟到了。")
            expect(page.locator("#focus-extend")).to_be_visible()
            assert snapshot()["session"]["elapsed_seconds"] == 60
            assert "rewards" not in snapshot()
            capture("focus-time-elapsed.png")
            page.locator("#focus-extend").click()
            expect(page.locator("#focus-stage")).to_have_text("专注中")
            assert snapshot()["session"]["id"] == active["id"]
            assert snapshot()["session"]["focus_minutes"] == 6
            page.locator("#focus-finish").click()
            expect(page.locator("#focus-stage")).to_have_text("已结束")
            assert snapshot()["session"]["elapsed_seconds"] >= 60
            page.locator("#focus-history-open").click()
            expect(page.locator("#focus-history-dialog")).to_be_visible()
            expect(page.locator("#focus-progress")).to_have_value("")
            page.locator("#focus-progress").fill("第一批商品资料整理完了")
            page.locator("#focus-progress-form button").click()
            expect(page.locator("#focus-progress-result")).to_contain_text("已收进记忆手札")
            capture("focus-user-progress.png")
            page.locator('[data-close="focus-history-dialog"]').click()
            page.locator('[data-close="nook-dialog"]').click()
            page.locator("#open-memory").click()
            expect(page.locator("#memory-content")).to_contain_text("第一批商品资料整理完了")
            page.keyboard.press("Escape")
            # A fresh anonymous activity remains optional and stoppable from chat.
            page.locator("#open-focus").click()
            page.locator("#focus-intention").fill("")
            page.locator("#focus-start").click()
            expect(page.locator("#focus-mini")).to_be_visible()
            assert snapshot()["session"]["intention"] == ""
            page.locator("#message-input").fill("今天不想弄了")
            page.locator("#send-message").click()
            expect(page.locator("#messages")).to_contain_text("好，先到这里。")
            expect(page.locator("#focus-mini")).to_be_hidden(timeout=10000)
            assert snapshot()["session"]["phase"] == "ended"
            assert errors == [], errors
            return {
                "status": "passed",
                "identity": client.connect(),
                "session_id": active["id"],
                "checks": [
                    "chat and room entrances",
                    "editable natural-language confirmation",
                    "optional task name",
                    "320/768/1024/1440 layout",
                    "keyboard modal return",
                    "mini-window shares clock and can pause",
                    "pause survives reload",
                    "rain is explicit and can be stopped",
                    "real one-minute deadline",
                    "extension keeps same session",
                    "early finish preserves elapsed time",
                    "progress is blank until user reports it",
                    "progress reaches existing memory UI",
                    "natural-language end",
                    "no timer rewards or completion claim",
                ],
                "screenshots": screenshots,
                "browser_errors": errors,
                "language_quality": "not_run",
            }
        except Exception:
            capture("focus-failure.png")
            raise
        finally:
            (instance.directory / "focus-browser-errors.json").write_text(
                json.dumps(errors, ensure_ascii=False), encoding="utf-8"
            )
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".agent-tests"))
    parser.add_argument("--channel", default=None)
    args = parser.parse_args()
    instance = ManagedInstance(args.root, timeout=360)
    result: dict[str, Any] = {"status": "not_run"}
    print("Starting isolated focus acceptance: " + instance.run_id, flush=True)
    try:
        instance.start()
        result = smoke(instance, channel=args.channel)
    except ImportError:
        result = {"status": "blocked", "reason": "install the browser extra and browser runtime"}
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__, "reason": str(error)}
    finally:
        instance.stop()
        (instance.directory / "focus-results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps({"status": result["status"], "run_id": instance.run_id}, ensure_ascii=False)
        )
    if result["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
