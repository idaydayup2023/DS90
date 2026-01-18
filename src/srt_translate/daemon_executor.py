from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable


class DaemonExecutor:
    def __init__(self, max_workers: int, thread_name_prefix: str):
        self._max_workers = max(1, int(max_workers))
        self._prefix = thread_name_prefix
        self._q: queue.Queue[tuple[Future[Any], Callable[..., Any], tuple[Any, ...], dict[str, Any]] | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._shutdown = False
        for i in range(self._max_workers):
            t = threading.Thread(target=self._worker, name=f"{self._prefix}_{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        if self._shutdown:
            raise RuntimeError("executor is shut down")
        fut: Future[Any] = Future()
        self._q.put((fut, fn, args, kwargs))
        return fut

    def shutdown(self, wait: bool = False, cancel_futures: bool = False) -> None:
        self._shutdown = True
        if cancel_futures:
            while True:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    continue
                fut, _fn, _args, _kwargs = item
                fut.cancel()
        for _ in self._threads:
            self._q.put(None)
        if wait:
            for t in self._threads:
                t.join(timeout=1.0)

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            fut, fn, args, kwargs = item
            if fut.cancelled():
                continue
            try:
                res = fn(*args, **kwargs)
            except BaseException as e:
                fut.set_exception(e)
            else:
                fut.set_result(res)
