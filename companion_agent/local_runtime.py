"""Owned loopback engine for the Windows bundle and embedded Android runtime.

No fixed port, shared cookie, detached daemon, or dependency on a desktop server.
Windows uses a private stdio pipe; Android calls start_embedded in its own process.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import secrets
import socket
import sys
import time
from pathlib import Path
from threading import Lock, Thread
from typing import Any, BinaryIO

import uvicorn

from companion_agent.app import create_app
from companion_agent.credentials import CredentialStore


class InstanceLease:
    """An OS-released lease prevents two engines opening one installation's data."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.file: BinaryIO = (directory / "engine.lock").open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("这份本地数据已由另一个心隅窗口使用，请先关闭它。") from None

    def close(self) -> None:
        self.file.close()


class LocalRuntime:
    def __init__(self, directory: Path, *, credentials: CredentialStore | None = None) -> None:
        self.directory = directory.expanduser().resolve()
        self.lease = InstanceLease(self.directory)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            from companion_agent.local_data import apply_pending_restore

            apply_pending_restore(self.directory)
            cache = Path(__file__).with_name("assets") / "tokenizers"
            if cache.is_dir():
                os.environ["TIKTOKEN_CACHE_DIR"] = str(cache)
            self.token = secrets.token_urlsafe(32)
            self.socket.bind(("127.0.0.1", 0))
            self.port = self.socket.getsockname()[1]
            self.app = create_app(
                self.directory,
                client_token=self.token,
                credentials=credentials,
                background_services=False,
            )
            self.server = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    host="127.0.0.1",
                    port=self.port,
                    loop="asyncio",
                    http="h11",
                    ws="none",
                    access_log=False,
                    log_level="error",
                    log_config=None,
                    timeout_graceful_shutdown=5,
                )
            )
            self.thread = Thread(
                target=self.server.run,
                kwargs={"sockets": [self.socket]},
                name="xinyu-local-engine",
                daemon=True,
            )
        except BaseException:
            self.socket.close()
            self.lease.close()
            raise

    def start(self) -> dict[str, Any]:
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                self.stop()
                raise RuntimeError("本机记忆引擎未能启动，请检查数据目录后重试。")
            time.sleep(0.02)
        return {
            "protocol": 1,
            "endpoint": f"http://127.0.0.1:{self.port}",
            "token": self.token,
        }

    def stop(self) -> None:
        self.app.state.host.loop.cancel_all()
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=8)
        if self.thread.is_alive():
            # Do not unlock the database while an old runtime can still use it.
            raise RuntimeError("记忆引擎尚未停止，请稍后再试。")
        self.socket.close()
        self.lease.close()


_embedded: LocalRuntime | None = None
_embedded_lock = Lock()


def start_embedded(directory: str, android_context: Any = None) -> str:
    global _embedded
    with _embedded_lock:
        if _embedded is None:
            credentials = None
            if android_context is not None:
                from companion_agent.android_credentials import AndroidCredentialStore

                credentials = AndroidCredentialStore(Path(directory), android_context)
            runtime = LocalRuntime(Path(directory), credentials=credentials)
            try:
                result = runtime.start()
            except BaseException:
                runtime.stop()
                raise
            _embedded = runtime
        else:
            result = {
                "protocol": 1,
                "endpoint": f"http://127.0.0.1:{_embedded.port}",
                "token": _embedded.token,
            }
        return json.dumps(result)


def stop_embedded() -> None:
    global _embedded
    with _embedded_lock:
        if _embedded is not None:
            _embedded.stop()
            _embedded = None


def main() -> None:
    parser = argparse.ArgumentParser(description="心隅本地应用引擎")
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    runtime: LocalRuntime | None = None
    try:
        runtime = LocalRuntime(args.data_dir)
        # The parent consumes this line; never write it to a log file.
        print(json.dumps(runtime.start()), flush=True)
        # EOF means the owning app exited, even if it crashed. No orphan server.
        if sys.stdin is not None:
            for line in sys.stdin:
                if line.strip() == "stop":
                    break
    except Exception:
        print(
            json.dumps({"error": "本地引擎启动失败。请确认没有其他心隅窗口正在使用这份数据。"}),
            flush=True,
        )
        raise SystemExit(1) from None
    finally:
        if runtime is not None:
            runtime.stop()


if __name__ == "__main__":
    main()
