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
        """Pre-flight check: /api/health returns 200 OK."""
        with TestClient(app) as client:
            res = client.get("/api/health")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data.get("status"), "healthy")

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


if __name__ == "__main__":
    unittest.main()

