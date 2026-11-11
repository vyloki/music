"""
Wave Music - Locust High-Concurrency Load & Stress Test Harness
Simulates realistic user workflows under concurrent load:
- Home feed browsing
- Search autocomplete and full-text search
- Lyrics retrieval (with auto-sync calculation)
- Audio range streaming chunk buffering

Run with:
    ./venv/bin/pip install locust
    ./venv/bin/locust -f tests/load_test_locust.py --host http://0.0.0.0:8000
    Or headless:
    ./venv/bin/locust -f tests/load_test_locust.py --headless -u 50 -r 5 -t 30s --host http://0.0.0.0:8000
"""

from locust import HttpUser, task, between
import random

SEARCH_QUERIES = [
    "One Sun One Moon Telugu",
    "Samajavaragamana",
    "Chali Gaali Chuudduu",
    "Anirudh Telugu hit songs",
    "Aaya Sher Telugu",
    "Hukum Jailer",
    "Naatu Naatu",
    "Inkem Inkem Inkem Kaavaale",
]

TRACK_IDS = [
    "-xoVniQbg1Q",
    "dTiRoIgZfW4",
    "fgZ9pJbVA3c",
]


class WaveMusicUser(HttpUser):
    # Simulated user pacing (1 to 3 seconds pause between operations)
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Pre-flight health check on spawn."""
        self.client.get("/api/health")

    @task(5)
    def test_search_and_filter(self):
        """Simulate searching songs and filtering results."""
        q = random.choice(SEARCH_QUERIES)
        with self.client.get(f"/api/search?q={q}&limit=20", name="/api/search [Query]", catch_response=True) as resp:
            if resp.status_code == 200:
                results = resp.json()
                if isinstance(results, list):
                    resp.success()
                else:
                    resp.failure("Search response format invalid")
            else:
                resp.failure(f"Search returned status {resp.status_code}")

    @task(3)
    def test_lyrics_auto_sync(self):
        """Simulate fetching synced lyrics with Wave Auto-Sync Engine."""
        vid = random.choice(TRACK_IDS)
        params = {
            "title": "One Sun One Moon",
            "artist": "Anirudh Ravichander",
            "movie": "Jailer 2",
            "duration": 218,
            "language": "Telugu",
            "channel": "Sun Pictures",
        }
        with self.client.get(f"/api/lyrics/{vid}", params=params, name="/api/lyrics [Auto-Sync]", catch_response=True) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if "synced" in data:
                    resp.success()
                else:
                    resp.failure("Lyrics missing synced array")
            else:
                resp.failure(f"Lyrics returned status {resp.status_code}")

    @task(2)
    def test_audio_stream_header(self):
        """Simulate browser requesting initial 256KB audio range chunk."""
        vid = random.choice(TRACK_IDS)
        headers = {"Range": "bytes=0-262143"}
        with self.client.get(f"/api/stream/{vid}", headers=headers, name="/api/stream [Range Chunk]", catch_response=True) as resp:
            if resp.status_code in (200, 206, 302):
                resp.success()
            else:
                resp.failure(f"Audio stream returned unexpected status {resp.status_code}")

