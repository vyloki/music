---
name: wave-testing-qa
description: >-
  Testing standards, QA verification suites, and test runners specifically for the Wave Music application.
  Use when writing, running, or debugging tests for Wave's endpoints, services, authentication,
  audio streaming proxy, database models, or verifying bug fixes and pull requests.
---

# Wave Music App — Quality Assurance & Testing Standards

These standards define test execution, test fixture conventions, and regression verification for the Wave Music application.

---

## 1. Test Environment & Execution Rules

### 1.1 Python Virtual Environment
- **Always execute test commands with the virtual environment Python interpreter**:
  ```bash
  ./venv/bin/python -m pytest tests/
  ```
- Never use bare `python` or `python3` to avoid environment mismatch or system Python package conflicts.

### 1.2 Isolation & Non-Destructive Testing
- Tests must never delete or overwrite production user accounts or production playlist data.
- Use distinct test identifiers (e.g., email prefixes `test_runner_<uuid>@example.com`, playlist names `__test_pl_<uuid>__`).
- Clean up any test entities created during test execution in test fixtures or teardown blocks.

---

## 2. Test Suites by Domain

### 2.1 Health & Lifespan Verification
Verify that the application initializes, connects to MongoDB, builds indexes without crashing, and shuts down cleanly:
```python
from fastapi.testclient import TestClient
from app.main import app

def test_health_check_cached():
    with TestClient(app) as client:
        # First call: populates cache
        res1 = client.get("/api/health")
        assert res1.status_code == 200
        assert res1.json()["database"] == "connected"
        
        # Second call: fast cache hit
        res2 = client.get("/api/health")
        assert res2.status_code == 200
```

### 2.2 Security & Auth Flow Verification
```python
import pytest
from httpx import AsyncClient
from app.main import app
from app.utils.security import hash_password_async, verify_password_async

@pytest.mark.asyncio
async def test_async_password_hashing():
    password = "SuperSecretPassword123!"
    hashed = await hash_password_async(password)
    assert await verify_password_async(password, hashed) is True
    assert await verify_password_async("WrongPassword", hashed) is False

@pytest.mark.asyncio
async def test_auth_registration_and_login():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Register
        res = await client.post("/api/auth/register", json={
            "email": "test_user_qa@example.com",
            "username": "test_user_qa",
            "password": "ValidPassword123!"
        })
        assert res.status_code in (201, 409)  # 201 on first run, 409 if exists
        
        # Login
        login_res = await client.post("/api/auth/login", json={
            "email_or_username": "test_user_qa",
            "password": "ValidPassword123!"
        })
        assert login_res.status_code == 200
        data = login_res.json()
        assert "access_token" in data
        assert "refresh_token" in data
```

### 2.3 Search & L1 Cache Verification
```python
import pytest
from httpx import AsyncClient
from app.main import app
from app.utils.cache import search_l1_cache

@pytest.mark.asyncio
async def test_search_caching():
    search_l1_cache.clear()
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Moods endpoint (L1 cached)
        res1 = await client.get("/api/search/moods")
        assert res1.status_code == 200
        assert "moods" in res1.json()
        
        # Trending endpoint (L1 cached)
        res2 = await client.get("/api/search/trending")
        assert res2.status_code == 200
```

### 2.4 Playlists Atomic Operation & Lean Projection Verification
```python
@pytest.mark.asyncio
async def test_playlist_lean_projection(authenticated_client):
    # Fetch playlist list: should NOT return heavy full tracks array
    res = await authenticated_client.get("/api/playlists")
    assert res.status_code == 200
    playlists = res.json()["playlists"]
    for pl in playlists:
        assert "track_count" in pl
        assert "tracks" not in pl or len(pl.get("tracks", [])) <= 1
```

---

## 3. Automated Pre-Flight Test Script

Execute this command whenever verifying the full project integrity:
```bash
./venv/bin/python -c "
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.utils.security import hash_password_async, verify_password_async
from app.utils.cache import TTLCache

# 1. Async security test
async def verify_security():
    h = await hash_password_async('WaveTestPass1!')
    assert await verify_password_async('WaveTestPass1!', h)
    assert not await verify_password_async('BadPass', h)
asyncio.run(verify_security())

# 2. Endpoint test
with TestClient(app) as client:
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/search/moods').status_code == 200
    assert client.get('/api/search/trending').status_code == 200

print('ALL PRE-FLIGHT CHECKS PASSED!')
"
```

