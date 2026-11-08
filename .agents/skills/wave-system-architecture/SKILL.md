---
name: wave-system-architecture
description: >-
  System architecture, backend patterns, and performance standards specifically for the Wave Music application.
  Use when designing, extending, or refactoring Wave's FastAPI routes, services, MongoDB queries,
  caching layers, background tasks, audio streaming proxy, or authentication security.
---

# Wave Music App — Backend System Architecture & Standards

These standards govern backend development, API contracts, database operations, and audio proxying for the Wave Music application.

---

## 1. Project Directory Structure & Responsibility

```
app/
├── config.py           # Pydantic Settings (ENV variables, secrets, debug flags)
├── database.py         # MongoDB connection lifecycle, client management, index verification
├── main.py             # FastAPI entrypoint, lifespan startup/shutdown, global error handlers
├── models/             # Pydantic request/response schemas (auth, playlist, track)
├── routes/             # FastAPI APIRouters (auth, search, stream, extract, playlist, history, lyrics, etc.)
├── services/           # Business domain services (youtube_service, stream_service, extractor_service, etc.)
│   └── http_client.py  # Persistent shared AsyncClient connection pool
├── tasks.py            # Async background task execution & GC protection
└── utils/              # Pure utility modules
    ├── cache.py        # In-memory thread-safe TTLCache singletons
    ├── db.py           # Safe BSON ObjectId conversion (to_object_id)
    └── security.py     # Async bcrypt hashing, JWT creation/validation, get_current_user
```

---

## 2. Core Architectural Standards

### 2.1 Database Operations & Safe BSON Identifiers
- Always use `app.utils.db.to_object_id(val, entity_name)` when parsing user-supplied IDs for MongoDB queries. Never instantiate `ObjectId(raw_id)` directly in routes without catching `InvalidId`, as invalid IDs must return `400 Bad Request`, not `500 Internal Server Error`.
- Always project fields in queries. Never load entire documents or large arrays (`tracks`, `formats`, `raw_info`) when only summary metadata is needed.
- Enforce atomic database operations (`$push`, `$pull`, `$inc`, `$set`) to maintain counter consistency (e.g., `track_count`) and prevent lost updates under concurrency.

### 2.2 Multi-Tier Caching Guidelines
1. **L1 In-Memory Cache (`app.utils.cache.TTLCache`)**:
   - `search_l1_cache`: Caches search results (`ttl=300s`), trending (`ttl=600s`), and moods (`ttl=3600s`).
   - `home_feed_cache`: Caches personalized and global home recommendation feeds (`ttl=600s`).
   - `health_cache`: Caches MongoDB ping status (`ttl=5s`) to prevent database thrashing from frequent health probes.
   - `lyrics_l1_cache`: Caches retrieved and normalized lyrics (`ttl=3600s`).
2. **L2 MongoDB Collections with TTL Indexes**:
   - `stream_cache`: Expire after 7 days (`cached_at`).
   - `song_cache`: Expire after 7 days (`cached_at`).
   - `search_cache`: Expire after 24 hours (`cached_at`).
   - `recommendation_cache`: Expire after 12 hours (`cached_at`).
   - `lyrics_cache`: Expire after 30 days (`cached_at`). Negative misses expire after 24 hours.

### 2.3 Audio & Media Streaming Proxy
- **Persistent HTTP Pool**: Always use `get_stream_client()` from `app.services.http_client`. Never allocate ad-hoc `httpx.AsyncClient` inside streaming routes.
- **Chunk Buffers**:
  - Real-time audio streaming: Use `262144` bytes (256 KB) buffer chunks.
  - Media downloads: Use `524288` bytes (512 KB) buffer chunks.
- **Range Header & Fast Probing**:
  - `HEAD /api/stream/{video_id}` must check `stream_cache` first and return instant HTTP 200 headers (`Content-Length`, `Accept-Ranges`) if metadata is present, bypassing external Google roundtrips.
  - Forward client `Range` headers to the upstream stream URL.
  - On HTTP 403 Forbidden upstream responses, trigger `force_refresh=True` to fetch a fresh signed playback URL and retry.

### 2.4 Asynchronous Concurrency & Event Loop Protection
- Offload CPU-bound bcrypt operations to `asyncio.to_thread` via `hash_password_async` and `verify_password_async`.
- Keep bcrypt work factor tuned to `rounds=11` (sub-70ms hashing latency with high cryptographic strength).
- Protect multi-query external fan-outs with `asyncio.Semaphore(3)` in `app.services.youtube_service`.
- Make non-critical writes (e.g., listening history recording, co-listen transition graph updates) non-blocking by dispatching them to `BackgroundTasks`.

