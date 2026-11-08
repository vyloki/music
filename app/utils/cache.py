"""
In-memory TTL and LRU Cache utility.
Zero-dependency thread-safe cache using collections.OrderedDict and time.monotonic.
"""

from collections import OrderedDict
import functools
import threading
import time
from typing import Any, Callable, Optional


class TTLCache:
    """Thread-safe in-memory cache with Time-To-Live (TTL) and LRU eviction."""

    def __init__(self, maxsize: int = 500, default_ttl: float = 300.0):
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key not in self._data:
                return default
            val, expiry = self._data[key]
            if time.monotonic() > expiry:
                del self._data[key]
                return default
            # Mark recently used (move to end)
            self._data.move_to_end(key)
            return val

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            ttl_val = self.default_ttl if ttl is None else ttl
            expiry = time.monotonic() + ttl_val
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, expiry)
            # Evict oldest if maxsize exceeded
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        with self._lock:
            # Clean expired items on length check
            now = time.monotonic()
            expired = [k for k, (_, exp) in self._data.items() if now > exp]
            for k in expired:
                del self._data[k]
            return len(self._data)


# Shared global cache singletons
search_l1_cache = TTLCache(maxsize=500, default_ttl=300.0)
home_feed_cache = TTLCache(maxsize=100, default_ttl=600.0)
lyrics_l1_cache = TTLCache(maxsize=1000, default_ttl=3600.0)
health_cache = TTLCache(maxsize=10, default_ttl=5.0)
artist_l1_cache = TTLCache(maxsize=200, default_ttl=600.0)

