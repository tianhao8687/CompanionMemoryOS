from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from companion_agent.testing.driver import Client, ManagedInstance, cleanup_run, run_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated real-process companion testing")
    parser.add_argument("command", choices=["serve", "run", "shell", "connect", "cleanup"])
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--root", type=Path, default=Path(".agent-tests"))
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--url")
    parser.add_argument("--token-env", default="COMPANION_TEST_TOKEN")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--local-embedding-url", help="explicit local http://127.0.0.1:<port>/v1")
    parser.add_argument("--settings", type=Path, help="non-secret exported settings for live runs")
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--max-calls", type=int, default=80)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--variant",
        choices=["full", "no_examples", "no_history", "no_old_conditions"],
        default="full",
    )
    args = parser.parse_args()
    if args.command == "cleanup":
        if args.run_dir is None:
            parser.error("cleanup requires --run-dir for an owned, closed test run")
        cleanup_run(args.run_dir)
        print(json.dumps({"status": "passed", "operation": "cleanup"}))
        return
    if args.command == "serve":
        import uvicorn

        from companion_agent.app import create_app
        from companion_agent.testing.control import TestControl

        if args.run_dir is None or args.port is None:
            parser.error("serve requires an owned run directory and port")
        control = TestControl(args.run_dir, os.environ.get(args.token_env, ""))
        uvicorn.run(
            create_app(args.run_dir / "data", testing=control),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )
        return
    if args.command == "connect":
        if not args.url:
            parser.error("connect requires --url")
        client = Client(args.url, os.environ.get(args.token_env, ""))
        print(json.dumps(client.connect(), ensure_ascii=False))
        shell(client)
        return
    settings = json.loads(args.settings.read_text(encoding="utf-8")) if args.settings else None
    if args.allow_live and settings is None:
        parser.error("live tests require explicit non-secret --settings and bounded quotas")
    instance = ManagedInstance(
        args.root,
        allow_live=args.allow_live,
        settings=settings,
        max_turns=args.max_turns,
        max_calls=args.max_calls,
        max_output_tokens=args.max_output_tokens,
        timeout=args.timeout,
        variant=args.variant,
        local_embedding_url=args.local_embedding_url,
    )
    try:
        client = instance.start()
        if args.command == "shell":
            print(
                json.dumps(
                    {"directory": str(instance.directory), "url": client.url, **client.identity},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            shell(client, instance)
        else:
            if args.scenario is None:
                parser.error("run requires --scenario")
            result = run_scenario(instance, json.loads(args.scenario.read_text(encoding="utf-8")))
            print(
                json.dumps(
                    {"status": result["status"], "report": str(instance.directory / "report.md")},
                    ensure_ascii=False,
                )
            )
            if result["status"] != "passed":
                raise SystemExit(2)
    finally:
        instance.stop()


def shell(client: Client, instance: ManagedInstance | None = None) -> None:
    """One JSON operation per line, retaining cookies and the owned process handle."""
    for line in sys.stdin:
        original: dict[str, Any] = {}
        output: dict[str, Any]
        try:
            request = json.loads(line)
            original = dict(request)
            operation = request.pop("operation")
            if operation == "stop":
                return
            if operation == "restart" and instance is not None:
                client = instance.restart()
                result: Any = client.identity
            elif operation in {
                "new_session",
                "send_message",
                "read_history",
                "read_state",
                "inspect_trace",
                "correct_memory",
                "forget_memory",
                "update_event",
                "advance_time",
                "connect",
            }:
                result = getattr(client, operation)(**request)
            else:
                raise ValueError("operation unavailable for this connection")
            output = {"status": "passed", "result": result}
        except Exception as error:
            output = {"status": "failed", "error_type": type(error).__name__}
        if instance:
            with (instance.directory / "interactive.jsonl").open("a", encoding="utf-8") as log:
                log.write(
                    json.dumps({"input": original, "output": output}, ensure_ascii=False) + "\n"
                )
        print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
