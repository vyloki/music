"""
Wave Music - API Pre-flight & Search Endpoint Tests
Verifies endpoint compilation, router health, moods, trending, and radio contracts.
"""

import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.utils.cache import search_l1_cache


class TestApiEndpoints(unittest.TestCase):

    def setUp(self):
        search_l1_cache.clear()

    def test_health_check(self):
        """Pre-flight check: /api/health returns 200 OK for GET and HEAD."""
        with TestClient(app) as client:
            res = client.get("/api/health")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data.get("status"), "healthy")

            head_res = client.head("/api/health")
            self.assertEqual(head_res.status_code, 200)
            self.assertEqual(head_res.content, b"")

    def test_production_debug_defaults(self):
        """Verify Settings.debug defaults safely to False for production deploys."""
        from app.config import Settings

        self.assertIs(Settings.model_fields["debug"].default, False)
        self.assertIs(Settings.parse_debug("INFO"), False)
        self.assertIs(Settings.parse_debug("false"), False)
        self.assertIs(Settings.parse_debug("true"), True)

    def test_search_moods(self):
        """Pre-flight check: /api/search/moods returns 200 OK with categories."""
        with TestClient(app) as client:
            res = client.get("/api/search/moods")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("moods", data)
            self.assertGreater(data.get("total", 0), 0)

    def test_search_trending(self):
        """Pre-flight check: /api/search/trending returns 200 OK."""
        with TestClient(app) as client:
            res = client.get("/api/search/trending?limit=5")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("tracks", data)

    def test_categories_endpoint(self):
        """Check: /api/recommendations/categories returns official browse categories."""
        with TestClient(app) as client:
            res = client.get("/api/recommendations/categories")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("categories", data)

    def test_search_suggestions(self):
        """Check: /api/search/suggestions returns 200 OK."""
        with TestClient(app) as client:
            res = client.get("/api/search/suggestions?q=anirudh")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("suggestions", data)

    def test_history_batch_endpoint(self):
        """Check: POST /api/history/batch accepts multiple entries cleanly."""
        with TestClient(app) as client:
            payload = {
                "entries": [
                    {
                        "video_id": "test_batch_1",
                        "title": "Hukum Reloaded",
                        "artist": "Anirudh Ravichander",
                        "thumbnail": "https://img.youtube.com/vi/test_batch_1/hqdefault.jpg",
                        "duration": 210,
                        "movie": "Jailer",
                        "language": "Telugu"
                    },
                    {
                        "video_id": "test_batch_2",
                        "title": "Chaleya",
                        "artist": "Anirudh Ravichander",
                        "thumbnail": "https://img.youtube.com/vi/test_batch_2/hqdefault.jpg",
                        "duration": 195,
                        "movie": "Jawan",
                        "language": "Hindi"
                    }
                ]
            }
            res = client.post("/api/history/batch", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data.get("status"), "recorded")
            self.assertEqual(data.get("count"), 2)

    def test_frontend_search_deduplication_guards(self):
        """Verify that frontend/js/app.js implements in-flight deduplication and replaceState."""
        with open("frontend/js/app.js", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("currentSearchAbortController", content)
        self.assertIn("currentSearchPromise", content)
        self.assertIn("activeSearchQuery === trimmed", content)
        self.assertIn("history.replaceState", content)
        self.assertIn("currentSuggestionAbortController", content)
        self.assertIn("suggestionMemoryCache", content)

    def test_frontend_auth_batch_sync(self):
        """Verify that frontend/js/auth.js uses atomic batch sync instead of a 10x loop."""
        with open("frontend/js/auth.js", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/api/history/batch", content)
        self.assertNotIn("for (const t of list.slice(0, 10)) {\n                    API.post('/api/history'", content)



if __name__ == "__main__":
    unittest.main()

