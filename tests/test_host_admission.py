"""Read snapshots must not masquerade as an in-flight chat writer."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException

from companion_agent.app import RomanceHost


def test_read_snapshot_wait_does_not_reject_a_new_writer(tmp_path):
    host = RomanceHost(tmp_path)
    original = host.lock
    attempted = Event()

    class ObservedLock:
        def acquire(self, blocking=True):
            attempted.set()
            return original.acquire(blocking)

        def release(self):
            original.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *args):
            self.release()

    host.lock = ObservedLock()

    def write():
        with host.exclusive():
            return "admitted"

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with original:
                future = pool.submit(write)
                assert attempted.wait(5)
            assert future.result(timeout=5) == "admitted"
    finally:
        host.memory.close_indexer()


def test_active_writer_still_rejects_another_writer_and_allows_reentry(tmp_path):
    host = RomanceHost(tmp_path)

    def second_writer():
        with host.exclusive():
            return True

    try:
        with ThreadPoolExecutor(max_workers=1) as pool, host.exclusive():
            with host.exclusive():
                pass
            with pytest.raises(HTTPException) as rejected:
                pool.submit(second_writer).result(timeout=5)
            assert rejected.value.status_code == 409
    finally:
        host.memory.close_indexer()
