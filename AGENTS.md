# Wave Music App — Engineering & Design Directives

These directives must be strictly followed when building, updating, refactoring, or testing any component of the Wave Music application.

---

## 1. Professional System Design & Architecture Directives
- **Layered Architecture**: Route handlers (`app/routes/*`) must never contain raw database queries, long iterations, or direct external HTTP requests. Delegate all business logic to domain services (`app/services/*`).
- **Safe Database Identifiers**: Always convert user-provided identifiers using `app.utils.db.to_object_id()`. Invalid IDs must return `400 Bad Request`, never `500 Internal Server Error`.
- **Atomic Operations & Lean Projections**: Never read-modify-write documents. Always use atomic MongoDB operators (`$set`, `$inc`, `$push`, `$pull`). In collection listing endpoints (`/api/playlists`, `/api/extract/history`), project only summary metadata; omit large arrays (`tracks`, `formats`).
- **Async Event Loop Integrity**: Never execute blocking calls on the main event loop. Offload CPU-heavy operations (bcrypt password hashing) to worker threads using `hash_password_async` with `rounds=11`.
- **Persistent HTTP Pooling**: Always reuse the shared connection pools (`get_http_client()`, `get_stream_client()`) from `app.services.http_client`. Never instantiate ad-hoc `httpx.AsyncClient` inside request handlers.
- **Multi-Tier Caching**: Protect downstream services with the L1 in-memory `TTLCache` (`app/utils/cache.py`) and MongoDB TTL collections.

---

## 2. Professional UI & Frontend Directives
- **Minimalist Aesthetic (Strict Zero-Clutter)**: 
  - Zero decorative icons on buttons, badges, table columns, or headers.
  - Zero flag emojis or regional flag graphics (use standard ISO text codes: `TEL`, `TAM`, `HIN`, `ENG`).
  - No colored badge overload; use clean typographic contrast.
- **Audio Player State Machine**:
  - Maintain clean audio state transitions (`IDLE`, `LOADING`, `PLAYING`, `PAUSED`, `ERROR`).
  - Set `audio.crossOrigin = "anonymous"` to allow Web Audio API / canvas visualization.
  - Detach active `timeupdate` listeners during manual slider dragging to eliminate thumb stutter.
- **XSS Prevention**: Never insert untrusted strings into `innerHTML`. Always use `escapeHtml()` or native textContent bindings.

---

## 3. Professional Quality Assurance & Testing Directives
- **Virtual Environment Execution**: All Python commands, tests, and server processes must strictly run with `./venv/bin/python`.
- **Test Before Delivering**: Before completing any task, execute end-to-end verification verifying that:
  1. All modified Python files compile cleanly (`python -m py_compile`).
  2. The full application and all routers import without error.
  3. Pre-flight endpoint checks (`/api/health`, `/api/search/moods`, `/api/search/trending`) return `200 OK`.
- **Zero-Flake & Isolated Testing**: Never mutate production databases or leave test artifacts uncleaned.

