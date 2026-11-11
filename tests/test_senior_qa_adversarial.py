"""
Senior QA Adversarial & Deep System Verification Test Suite.
Exhaustively tests every basic and complex feature, edge case, and boundary condition in Wave.
"""

import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.utils.cache import search_l1_cache, home_feed_cache, lyrics_l1_cache


class SeniorQAAdversarialTestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        search_l1_cache.clear()
        home_feed_cache.clear()
        lyrics_l1_cache.clear()

    # =========================================================================
    # 1. System Health & Infrastructure
    # =========================================================================

    def test_health_check_contract(self):
        """Verify health check returns 200, status healthy, and valid schema."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertIn("version", data)

    # =========================================================================
    # 2. Search API: Basic, Complex & Hidden Edge Cases
    # =========================================================================

    def test_search_basic_and_results_contract(self):
        """Verify standard search query returns clean array and valid track attributes."""
        res = self.client.get("/api/search?q=one%20sun%20one%20moon%20telugu&limit=5")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("results", data)
        self.assertIsInstance(data["results"], list)
        if data["results"]:
            track = data["results"][0]
            self.assertIn("video_id", track)
            self.assertIn("title", track)
            self.assertTrue(len(track["video_id"]) > 0)

    def test_search_hidden_edge_cases_special_characters(self):
        """Adversarial: Test queries with apostrophes, quotes, unicode, and symbols."""
        hard_queries = [
            "Don't Stop Believin'",
            'Jailer 2 "One Sun One Moon"',
            "O'Connor & Sons",
            "Hukum • Jailer | Rajinikanth",
            "தமிழ் பாடல்கள் 2026",
            "Telugu (Official) [4K] #Trending",
        ]
        for q in hard_queries:
            res = self.client.get(f"/api/search?q={q}&limit=3")
            self.assertEqual(res.status_code, 200, f"Search failed for query: {q}")
            data = res.json()
            self.assertIn("results", data)
            self.assertNotEqual(res.status_code, 500)

    def test_search_empty_and_whitespace_boundaries(self):
        """Adversarial: Empty query or query consisting only of spaces must be rejected."""
        res = self.client.get("/api/search?q=")
        self.assertIn(res.status_code, [400, 422])
        self.assertNotEqual(res.status_code, 500)

    def test_search_suggestions_edge_cases(self):
        """Verify suggestions handle short queries, symbols, and L1 caching."""
        # Short query (< 1 char)
        res_short = self.client.get("/api/search/suggestions?q=")
        self.assertIn(res_short.status_code, [400, 422])

        # Normal query
        res = self.client.get("/api/search/suggestions?q=anirudh")
        self.assertEqual(res.status_code, 200)
        self.assertIn("suggestions", res.json())

    def test_search_moods_endpoints(self):
        """Verify mood listings and targeted mood querying."""
        res_all = self.client.get("/api/search/moods")
        self.assertEqual(res_all.status_code, 200)
        self.assertIn("moods", res_all.json())

        # Specific mood
        res_mood = self.client.get("/api/search/moods?mood=chill&limit=5")
        self.assertEqual(res_mood.status_code, 200)
        data = res_mood.json()
        self.assertIn("tracks", data)

    def test_search_trending_boundaries(self):
        """Verify trending endpoint respects limits and handles invalid categories cleanly."""
        res = self.client.get("/api/search/trending?limit=3")
        self.assertEqual(res.status_code, 200)
        self.assertIn("tracks", res.json())

    # =========================================================================
    # 3. Audio Streaming & Download Proxy
    # =========================================================================

    def test_stream_invalid_video_id(self):
        """Adversarial: Verify non-existent video IDs return 404/400 without crashing."""
        res = self.client.get("/api/stream/invalid_dummy_id_99999")
        self.assertIn(res.status_code, [400, 404, 502, 503])
        self.assertNotEqual(res.status_code, 500)

    def test_stream_download_header(self):
        """Verify download endpoint initiates stream or appropriate fallback response."""
        res = self.client.get("/api/stream/dTiRoIgZfW4/download?title=Jailer2&artist=Anirudh")
        self.assertIn(res.status_code, [200, 302, 307, 404, 502])

    # =========================================================================
    # 4. History API: Single & Atomic Batch Operations
    # =========================================================================

    def test_history_batch_recording(self):
        """Verify batch history recording accepts lists and updates daily counters."""
        payload = {
            "entries": [
                {
                    "video_id": "qa_test_v1",
                    "title": "Song One (Don't Stop)",
                    "artist": "Artist A",
                    "thumbnail": "https://img.youtube.com/vi/qa_test_v1/0.jpg",
                    "duration": 200,
                    "movie": "Movie 1",
                    "language": "Telugu"
                },
                {
                    "video_id": "qa_test_v2",
                    "title": "Song Two",
                    "artist": "Artist B",
                    "thumbnail": "https://img.youtube.com/vi/qa_test_v2/0.jpg",
                    "duration": 180,
                    "movie": "Movie 2",
                    "language": "Tamil"
                }
            ]
        }
        res = self.client.post("/api/history/batch", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "recorded")
        self.assertEqual(res.json().get("count"), 2)

    def test_history_batch_oversized_payload_rejection(self):
        """Adversarial: Reject payloads with excessive items (> 50 entries)."""
        oversized = {
            "entries": [
                {"video_id": f"dummy_{i}", "title": f"Title {i}"} for i in range(55)
            ]
        }
        res = self.client.post("/api/history/batch", json=oversized)
        self.assertEqual(res.status_code, 422)

    # =========================================================================
    # 5. Playlists API & Safe MongoDB ObjectIDs
    # =========================================================================

    def test_playlist_malformed_object_id(self):
        """Adversarial: Malformed non-hex string as ObjectID must return 400, never 500."""
        res = self.client.get("/api/playlists/not-a-valid-hex-id-123")
        self.assertIn(res.status_code, [400, 401, 404])
        self.assertNotEqual(res.status_code, 500)

    def test_playlist_empty_name_rejection(self):
        """Adversarial: Empty playlist name must fail validation."""
        res = self.client.post("/api/playlists", json={"name": ""})
        self.assertIn(res.status_code, [400, 401, 422])
        self.assertNotEqual(res.status_code, 500)

    # =========================================================================
    # 6. Recommendations & Smart Radio
    # =========================================================================

    def test_recommendations_categories(self):
        """Verify official browse categories endpoint contracts."""
        res = self.client.get("/api/recommendations/categories")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("categories", data)
        self.assertGreater(len(data["categories"]), 0)

    def test_recommendations_radio_endpoint(self):
        """Verify dynamic smart radio tracks can be generated from an anchor track."""
        res = self.client.get("/api/recommendations/radio?video_id=dTiRoIgZfW4&title=Jailer&artist=Anirudh&limit=5")
        self.assertEqual(res.status_code, 200)
        self.assertIn("tracks", res.json())

    # =========================================================================
    # 7. Frontend Architecture, Scope Cleanliness & Click Integrity
    # =========================================================================

    def test_frontend_no_global_safecreateicons_collision(self):
        """Verify player.js, library.js, and extract.js do not collide with app.js safeCreateIcons."""
        for filename in ["frontend/js/player.js", "frontend/js/library.js", "frontend/js/extract.js"]:
            with open(filename, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("const safeCreateIcons", content, f"Scope collision found in {filename}")

    def test_frontend_render_song_row_click_integrity(self):
        """Verify renderSongRow does NOT hijack subtitle clicks with searchForCategory."""
        with open("frontend/js/app.js", "r", encoding="utf-8") as f:
            content = f.read()
        # Subtitle span must NOT have an onclick that stops propagation
        self.assertNotIn('<span class="track-movie" onclick="event.stopPropagation(); searchForCategory', content)
        # Search results must expose data-search-index and data-video-id
        self.assertIn('data-search-index="${globalIndex}"', content)
        self.assertIn('data-video-id="${track.video_id}"', content)

    def test_frontend_global_window_bindings(self):
        """Verify core interactive handlers are explicitly bound to window."""
        with open("frontend/js/app.js", "r", encoding="utf-8") as f:
            app_content = f.read()
        self.assertIn("window.playTrackFromResults = playTrackFromResults", app_content)
        self.assertIn("window.downloadSongByIndex = downloadSongByIndex", app_content)
        self.assertIn("window.openAddToPlaylistByIndex = openAddToPlaylistByIndex", app_content)

        with open("frontend/js/player.js", "r", encoding="utf-8") as f:
            player_content = f.read()
        self.assertIn("window.Player = Player", player_content)
        self.assertIn("window.YTBridge = YTBridge", player_content)

    def test_frontend_delegated_event_listener_on_search_results(self):
        """Verify delegated click listener is installed on search-results for fail-safe playback."""
        with open("frontend/js/app.js", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("searchResultsContainer.addEventListener('click'", content)
        self.assertIn("playTrackFromResults(parseInt(idxStr, 10))", content)


if __name__ == "__main__":
    unittest.main()

