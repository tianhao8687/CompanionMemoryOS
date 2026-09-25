"""Run real controls and correlate the completed stream with storage and diagnostics.

Install .[browser] and `python -m playwright install chromium`, or use --channel msedge.
Only the driver-created synthetic instance is accessed. No browser profile is reused.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from companion_agent.testing.driver import ManagedInstance


def smoke(instance: ManagedInstance, *, channel: str | None = None) -> dict[str, Any]:
    from playwright.sync_api import expect, sync_playwright

    errors: list[str] = []
    client = instance.client
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=channel)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900}, locale="zh-CN", reduced_motion="reduce"
        )
        page = context.new_page()
        # Chromium does not reliably retain streamed bodies for Network.getResponseBody.
        # Observe a clone in the page; the original response and request stay untouched.
        page.add_init_script("""(() => {
          const originalFetch = window.fetch.bind(window);
          window.__chatStreamEvidence = null;
          window.fetch = async (...args) => {
            const response = await originalFetch(...args);
            if (new URL(response.url).pathname === '/api/chat/stream') {
              const evidence = {status: response.status, finished: false};
              window.__chatStreamEvidence = evidence;
              response.clone().text().then(body => {
                evidence.body = body; evidence.finished = true;
              }, error => {
                evidence.error = String(error); evidence.finished = true;
              });
            }
            return response;
          };
        })();""")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "requestfailed", lambda request: errors.append(request.url + " " + str(request.failure))
        )
        try:
            page.goto(client.url)
            expect(page.locator("#new-chat")).to_be_enabled()
            with page.expect_response(
                lambda r: r.url.endswith("/api/conversations") and r.request.method == "POST"
            ) as created:
                page.locator("#new-chat").click()
            conversation = created.value.json()["id"]
            utterance = "以后不要分析我的情绪。"
            page.locator("#message-input").fill(utterance)
            with page.expect_response(lambda r: r.url.endswith("/api/chat/stream")) as completed:
                page.locator("#send-message").click()
            assert completed.value.status == 200
            expect(page.locator("#typing")).to_be_hidden(timeout=30000)
            page.wait_for_function("window.__chatStreamEvidence?.finished", timeout=30000)
            wire = page.evaluate("window.__chatStreamEvidence")
            if wire.get("error"):
                raise AssertionError("browser stream observer failed: " + wire["error"])
            events = [json.loads(line) for line in wire["body"].splitlines() if line]
            if (
                not events
                or events[-1]["type"] != "done"
                or any(e["type"] == "error" for e in events)
            ):
                raise AssertionError("web stream did not finish successfully")
            result = next(e["result"] for e in events if e["type"] == "result")
            expect(page.locator("#typing")).to_be_hidden()
            expect(page.locator("#chat-error")).to_be_hidden()
            expect(page.locator("#messages")).to_contain_text(result["assistant"]["content"])
            history = client.read_history(conversation)
            assert result["assistant"]["id"] in {turn["id"] for turn in history}
            trace = client.inspect_trace(result["trace_id"])
            assert trace["request_id"] == result["user"]["request_id"]
            assert trace["result"]["assistant"]["id"] == result["assistant"]["id"]
            page.screenshot(
                path=str(instance.directory / "web-chat.png"), full_page=True, animations="disabled"
            )
            page.locator("#open-memory").click()
            expect(page.locator("#memory-dialog")).to_be_visible()
            expect(page.locator("#memory-content")).to_contain_text("不要分析我的情绪")
            page.screenshot(
                path=str(instance.directory / "web-memory.png"),
                full_page=True,
                animations="disabled",
            )
            page.locator('[data-close="memory-dialog"]').click()
            page.reload()
            expect(page.locator("#messages")).to_contain_text(utterance)
            expect(page.locator("#messages")).to_contain_text(result["assistant"]["content"])
            if errors:
                raise AssertionError("browser errors were observed")
            return {
                "status": "passed",
                "level": "web-real-process-offline-model",
                "identity": client.connect(),
                "conversation": conversation,
                "request_id": trace["request_id"],
                "trace": trace,
                "events": events,
                "screenshots": ["web-chat.png", "web-memory.png"],
                "browser_errors": errors,
                "language_quality": "not_run",
                "cancel_retry_web": "not_run",
            }
        except Exception:
            page.screenshot(path=str(instance.directory / "web-failure.png"), full_page=True)
            raise
        finally:
            (instance.directory / "browser-errors.json").write_text(
                json.dumps(errors, ensure_ascii=False), encoding="utf-8"
            )
            if errors:
                page.screenshot(path=str(instance.directory / "web-failure.png"), full_page=True)
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".agent-tests"))
    parser.add_argument("--channel", default=None)
    args = parser.parse_args()
    instance = ManagedInstance(args.root)
    result: dict[str, Any] = {"status": "not_run"}
    try:
        instance.start()
        result = smoke(instance, channel=args.channel)
    except ImportError:
        result = {"status": "blocked", "reason": "install the browser extra and browser runtime"}
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__, "reason": str(error)}
    finally:
        instance.stop()
        (instance.directory / "web-results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {"status": result["status"], "evidence": str(instance.directory)},
                ensure_ascii=False,
            )
        )
    if result["status"] != "passed":
        raise SystemExit(2)


def check_failure_controls(
    instance: ManagedInstance, set_transport_mode: Callable[[str], None], *, channel: str
) -> dict[str, Any]:
    """Browser acceptance with the local HTTP fixture used by test_process_stream.

    Faults are injected in that model transport, never via a fake application chat route.
    """
    from playwright.sync_api import expect, sync_playwright

    client = instance.client
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=channel)
        page = browser.new_page(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(client.url)
            with page.expect_response(
                lambda r: r.url.endswith("/api/conversations") and r.request.method == "POST"
            ) as created:
                page.locator("#new-chat").click()
            conversation = created.value.json()["id"]
            set_transport_mode("error")
            page.locator("#message-input").fill("验证失败后重试。")
            page.locator("#send-message").click()
            expect(page.locator("#chat-error")).to_be_visible(timeout=15000)
            history = client.read_history(conversation)
            assert [t["role"] for t in history] == ["user"]
            original_id = history[0]["request_id"]
            set_transport_mode("normal")
            page.locator("#retry-message").click()
            expect(page.locator("#chat-error")).to_be_hidden()
            expect(page.locator("#typing")).to_be_hidden(timeout=15000)
            expect(page.locator("#messages .message.assistant")).to_have_count(1)
            history = client.read_history(conversation)
            assert [t["role"] for t in history] == ["user", "assistant"]
            assert history[0]["request_id"] == original_id
            set_transport_mode("slow")
            page.locator("#message-input").fill("验证流中取消。")
            page.locator("#send-message").click()
            expect(page.locator("#messages .message.assistant")).to_have_count(2, timeout=15000)
            page.locator("#cancel-run").click()
            expect(page.locator("#chat-error")).to_be_visible(timeout=15000)
            expect(page.locator("#typing")).to_be_hidden()
            history = client.read_history(conversation)
            assert [t["role"] for t in history] == ["user", "assistant", "user"]
            assert page.locator("#messages .message.assistant").count() == 1
            traces = client.request(
                "GET",
                f"/api/testing/traces?conversation_id={conversation}"
                + "&request_id="
                + history[-1]["request_id"],
            )
            assert traces and traces[-1]["status"] == "failed"
            page.screenshot(
                path=str(instance.directory / "web-cancel.png"),
                full_page=True,
                animations="disabled",
            )
            assert not errors
            return {
                "status": "passed",
                "level": "web-real-process-local-http-model-fixture",
                "identity": client.connect(),
                "conversation": conversation,
                "retry_request_id": original_id,
                "cancel_traces": traces,
                "browser_errors": errors,
                "screenshot": "web-cancel.png",
            }
        finally:
            browser.close()


if __name__ == "__main__":
    main()
