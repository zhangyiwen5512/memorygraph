"""Tests for the QueryCache."""
import threading

from memorygraph.storage.cache import QueryCache


class TestQueryCache:
    def test_put_and_get(self):
        cache = QueryCache(maxsize=10)
        cache.put("key1", [{"a": 1}])
        assert cache.get("key1") == [{"a": 1}]

    def test_get_missing_returns_none(self):
        cache = QueryCache(maxsize=10)
        assert cache.get("nonexistent") is None

    def test_evicts_oldest_when_full(self):
        cache = QueryCache(maxsize=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # evicts oldest
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_get_refreshes_timestamp(self):
        cache = QueryCache(maxsize=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # refreshes "a"
        cache.put("c", 3)  # evicts "b" (oldest)
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_invalidate_file(self):
        cache = QueryCache(maxsize=10)
        cache.put("search:foo:10", [1])
        cache.put("node:bar", [2])
        cache.put("callers:foo:1", [3])
        cache.invalidate_file("foo")
        assert cache.get("search:foo:10") is None
        assert cache.get("callers:foo:1") is None
        assert cache.get("node:bar") == [2]

    def test_invalidate_file_no_substring_false_positive(self):
        """M1 regression: /foo/bar.py must not match /foo/bar_other.py."""
        cache = QueryCache(maxsize=10)
        cache.put("callers:func:/home/project/foo/bar.py:3", [1])
        cache.put("callers:func:/home/project/foo/bar_other.py:3", [2])
        cache.invalidate_file("/home/project/foo/bar.py")
        assert cache.get("callers:func:/home/project/foo/bar.py:3") is None
        # bar_other.py should NOT be evicted by substring match
        assert cache.get("callers:func:/home/project/foo/bar_other.py:3") == [2]

    def test_invalidate_file_colon_delimited_path(self):
        """Path :/home/foo.py: delimiter prevents false matches."""
        cache = QueryCache(maxsize=10)
        cache.put("callers:func:/a/b.py:3", [1])
        cache.put("search:query:10:/a/b.py", [2])
        cache.put("callees:func:/a/b.py:5", [3])
        cache.put("node:b.py", [4])  # no file path, just name
        cache.invalidate_file("/a/b.py")
        assert cache.get("callers:func:/a/b.py:3") is None
        assert cache.get("search:query:10:/a/b.py") is None
        assert cache.get("callees:func:/a/b.py:5") is None
        # 'node:b.py' key does not contain :/a/b.py: delimiter → not evicted
        assert cache.get("node:b.py") == [4]

    def test_clear(self):
        cache = QueryCache(maxsize=10)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert len(cache) == 0

    def test_thread_safety(self):
        cache = QueryCache(maxsize=100)
        errors = []

        def worker():
            try:
                for i in range(100):
                    cache.put(f"key-{threading.get_ident()}-{i}", i)
                    cache.get(f"key-{threading.get_ident()}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_hit_rate_empty_cache(self):
        """hit_rate() returns 0.0 when no hits or misses."""
        cache = QueryCache(maxsize=10)
        assert cache.hit_rate() == 0.0

    def test_hit_rate_with_hits(self):
        """hit_rate() returns correct ratio."""
        cache = QueryCache(maxsize=10)
        cache.put("a", 1)
        cache.get("a")  # hit
        cache.get("b")  # miss
        assert cache.hit_rate() == 0.5
