"""Thread-safe LRU cache for graph queries."""
import threading
import time


class QueryCache:
    """LRU cache for expensive graph traversals.

    Thread-safe. Invalidated on file changes.
    Cache keys are descriptive strings: 'search:<query>:<limit>',
    'callers:<name>:<depth>', 'node:<name>'.
    """

    def __init__(self, maxsize: int = 512):
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, object]] = {}
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> object | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries[key] = (time.monotonic(), entry[1])
                self._hits += 1
                return entry[1]
            self._misses += 1
            return None

    def put(self, key: str, value: object) -> None:
        with self._lock:
            if len(self._entries) >= self._maxsize:
                oldest_key = min(self._entries.items(),
                                 key=lambda x: x[1][0])[0]
                del self._entries[oldest_key]
            self._entries[key] = (time.monotonic(), value)

    def invalidate_file(self, file_path: str) -> None:
        """Remove all entries referencing a changed file.

        Uses colon-delimited matching to avoid false positives from
        substring collisions (e.g. ``/foo/bar.py`` matching
        ``/foo/bar_other.py``).
        """
        with self._lock:
            needle = f":{file_path}:"
            self._entries = {
                k: v for k, v in self._entries.items()
                if needle not in f":{k}:"
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0

    def hit_rate(self) -> float:
        with self._lock:
            total = self._hits + self._misses
            return self._hits / total if total > 0 else 0.0

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
