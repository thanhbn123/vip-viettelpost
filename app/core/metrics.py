"""Minimal in-process metrics (counters + duration summaries). Thread-safe.

Enough to observe provider latency and webhook outcomes on one instance; export to a
real metrics system is a later step (no extra dependency added here).
"""

import threading
from collections import defaultdict
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple, int] = defaultdict(int)
        self._timings: dict[tuple, list[float]] = {}

    @staticmethod
    def _key(name: str, labels: dict[str, Any]) -> tuple:
        return (name, tuple(sorted((k, str(v)) for k, v in labels.items())))

    def inc(self, name: str, **labels: Any) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += 1

    def observe(self, name: str, seconds: float, **labels: Any) -> None:
        key = self._key(name, labels)
        with self._lock:
            count, total, maximum = self._timings.get(key, (0, 0.0, 0.0))
            self._timings[key] = (count + 1, total + seconds, max(maximum, seconds))

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            counters = [
                {"name": n, "labels": dict(labels), "value": v}
                for (n, labels), v in sorted(self._counters.items())
            ]
            timings = [
                {
                    "name": n,
                    "labels": dict(labels),
                    "count": c,
                    "avg_ms": round(t / c * 1000, 1) if c else 0.0,
                    "max_ms": round(m * 1000, 1),
                }
                for (n, labels), (c, t, m) in sorted(self._timings.items())
            ]
        return {"counters": counters, "timings": timings}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._timings.clear()


metrics = Metrics()
