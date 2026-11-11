"""
Wave Music - Lyrics Accuracy & Auto-Sync Engine Test Suite
Adversarial tests validating:
1. Strict cross-language separation (Telugu never receives Tamil lyrics; Tamil never receives Telugu).
2. Wave Auto-Sync Engine bumper and duration-delta calculations (Saregama, Aditya Music, Sun Pictures, T-Series).
3. End-to-end API integration for multi-language tracks (e.g. One Sun One Moon / Jailer 2).
4. Automated cache contamination detection and purge.
"""

import unittest
import asyncio
from starlette.testclient import TestClient
from app.main import app
from app.services.lyrics_service import (
    _score_result_for_language,
    calculate_auto_sync_offset,
    get_lyrics,
    clean_song_titles,
)


class TestLyricsAutoSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_telugu_strictly_disqualifies_tamil_unicode(self):
        """Verify Telugu requests reject Tamil Unicode with -1000 score."""
        candidate = {
            "trackName": "One Sun One Moon (From Jailer 2)",
            "artistName": "Anirudh Ravichander",
            "albumName": "Jailer 2",
            "plainLyrics": "போர் தொடங்கிடும் ஓர் படை இறங்கிடும்\nஓர் கொடி பறந்திடும்",
        }
        score = _score_result_for_language(candidate, "Telugu", "Jailer 2")
        self.assertEqual(score, -1000, "Candidate with Tamil Unicode must be disqualified for Telugu")

    def test_telugu_strictly_disqualifies_tamil_phonetic_keywords(self):
        """Verify Telugu requests reject Romanized Tamil lyrics without Telugu script."""
        candidate = {
            "trackName": "Hukum Reloaded",
            "artistName": "Anirudh Ravichander",
            "albumName": "Jailer",
            "plainLyrics": "Innaikkum ennennaikkum oru thalaivanthaan\nPatthikkum ettutthikkum avan per chonnaa",
        }
        score = _score_result_for_language(candidate, "Telugu", "Jailer")
        self.assertEqual(score, -1000, "Romanized Tamil words must be disqualified for Telugu")

    def test_telugu_accepts_authentic_telugu_script(self):
        """Verify Telugu requests award high positive score to authentic Telugu Unicode."""
        candidate = {
            "trackName": "Chali Gaali Chuudduu",
            "artistName": "Haricharan",
            "albumName": "Mirai",
            "plainLyrics": "చలిగాలి చూద్దూ తెగ తుంటరి\nగిలిగింత పెడుతున్నది",
        }
        score = _score_result_for_language(candidate, "Telugu", "Mirai")
        self.assertGreater(score, 50, "Authentic Telugu script should receive high positive score")

    def test_tamil_strictly_disqualifies_telugu_unicode(self):
        """Verify Tamil requests reject Telugu Unicode with -1000 score."""
        candidate = {
            "trackName": "Samajavaragamana",
            "artistName": "Sid Sriram",
            "albumName": "Ala Vaikunthapurramuloo",
            "plainLyrics": "సామజవరగమనా నిను చూసి ఆగగలనా",
        }
        score = _score_result_for_language(candidate, "Tamil", "Ala Vaikunthapurramuloo")
        self.assertEqual(score, -1000, "Candidate with Telugu Unicode must be disqualified for Tamil")

    def test_tamil_accepts_authentic_tamil_script(self):
        """Verify Tamil requests award high positive score to authentic Tamil script."""
        candidate = {
            "trackName": "One Sun One Moon",
            "artistName": "Anirudh Ravichander",
            "albumName": "Jailer 2",
            "plainLyrics": "போர் தொடங்கிடும் ஓர் படை இறங்கிடும்",
        }
        score = _score_result_for_language(candidate, "Tamil", "Jailer 2")
        self.assertGreater(score, 50, "Authentic Tamil script should receive high score for Tamil request")

    def test_auto_sync_saregama_bumper_offset(self):
        """Verify Saregama channel intro bumper is detected and compensated."""
        # Saregama video with early vocal timestamp (<3s)
        offset = calculate_auto_sync_offset(
            channel="Saregama Telugu",
            uploader="Saregama Music",
            title="Super Hit Song",
            video_dur=215.0,
            lrc_dur=215.0,
            first_line_time=0.8,
        )
        self.assertEqual(offset, 4.5, "Saregama logo bumper must be offset by 4.5s")

    def test_auto_sync_aditya_music_bumper_offset(self):
        """Verify Aditya Music logo sting is detected and compensated."""
        offset = calculate_auto_sync_offset(
            channel="Aditya Music",
            uploader="",
            title="Aditya Music Hit Song",
            video_dur=220.0,
            lrc_dur=220.0,
            first_line_time=1.2,
        )
        self.assertEqual(offset, 3.5, "Aditya Music logo sting must be offset by 3.5s")

    def test_auto_sync_sun_pictures_bumper_offset(self):
        """Verify Sun Pictures fanfare bumper is detected and compensated."""
        offset = calculate_auto_sync_offset(
            channel="Sun Pictures",
            uploader="Sun Pictures",
            title="Jailer 2 Lyric Video",
            video_dur=218.0,
            lrc_dur=218.0,
            first_line_time=1.5,
        )
        self.assertEqual(offset, 5.0, "Sun Pictures bumper must be offset by 5.0s")

    def test_auto_sync_duration_delta_detection(self):
        """Verify duration discrepancies between YouTube video and studio track are offset."""
        # YouTube video has an 18s opening scene
        offset = calculate_auto_sync_offset(
            channel="Official Channel",
            uploader="",
            title="Movie Video Song",
            video_dur=247.0,
            lrc_dur=229.0,
            first_line_time=5.0,
        )
        self.assertEqual(offset, 18.0, "18s opening scene duration delta must be detected")

    def test_clean_track_zero_offset(self):
        """Verify studio track with matching duration and natural vocal onset receives 0.0s offset."""
        offset = calculate_auto_sync_offset(
            channel="Anirudh Official",
            uploader="",
            title="Clean Song",
            video_dur=218.0,
            lrc_dur=218.0,
            first_line_time=15.0,
        )
        self.assertEqual(offset, 0.0, "Clean matching track should have 0.0s offset")

    def test_get_lyrics_telugu_never_returns_tamil_lines(self):
        """End-to-End: Requesting Telugu lyrics for One Sun One Moon must NOT return Tamil lines."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(get_lyrics(
                track_name="One Sun One Moon",
                artist_name="Anirudh Ravichander",
                album_name="Jailer 2",
                duration=218,
                language="Telugu",
                video_id="test_telugu_onesun",
                channel="Sun Pictures",
            ))
            if res and res.get("synced_lyrics"):
                # Must NOT contain Tamil punchline
                for line in res["synced_lyrics"]:
                    t = line["text"].lower()
                    self.assertNotIn("thalaivanthaan", t, "Tamil phrase 'thalaivanthaan' found in Telugu lyrics!")
                    self.assertNotIn("chonnaa", t, "Tamil phrase 'chonnaa' found in Telugu lyrics!")
                    self.assertNotIn("innaikkum", t, "Tamil phrase 'innaikkum' found in Telugu lyrics!")
                    self.assertNotIn("போர்", line["text"], "Tamil script found in Telugu lyrics!")
        finally:
            loop.close()

    def test_api_lyrics_endpoint_telugu(self):
        """API Test: /api/lyrics/{video_id} with language=Telugu returns valid response with auto_offset."""
        res = self.client.get(
            "/api/lyrics/-xoVniQbg1Q",
            params={
                "title": "One Sun One Moon",
                "artist": "Anirudh Ravichander",
                "movie": "Jailer 2",
                "duration": 218,
                "language": "Telugu",
                "channel": "Sun Pictures",
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("video_id", data)
        self.assertIn("synced", data)
        self.assertIn("has_synced", data)
        self.assertIn("auto_offset", data)
        # Verify no Tamil text in synced lines
        for item in data.get("synced", []):
            txt = item["text"].lower()
            self.assertNotIn("thalaivanthaan", txt)
            self.assertNotIn("chonnaa", txt)


if __name__ == "__main__":
    unittest.main()

