"""
Wave Music - Official Music & Duration Guardrail Tests
Tests the filtering of unofficial channels, compilations, movies, and long audio,
ensuring queue, radio, and search return verified official songs under 6 minutes.
"""

import unittest
from app.services.youtube_service import (
    is_official_music_source,
    is_unofficial_source,
    is_compilation_or_junk,
    is_valid_single_song,
    classify_track_type,
    compute_track_quality_score,
    MAX_SONG_DURATION,
    MIN_SONG_DURATION,
)


class TestOfficialMusicFilter(unittest.TestCase):

    def test_official_labels_detection(self):
        """Official record labels must be identified as official music sources."""
        official_uploaders = [
            "T-Series",
            "T-Series Telugu",
            "T-Series Tamil",
            "T-Series Apna Punjab",
            "Aditya Music",
            "Aditya Music Telugu",
            "Aditya Movies",
            "Saregama Music",
            "Saregama Telugu",
            "Saregama South",
            "Sony Music South",
            "Sony Music India",
            "Zee Music Company",
            "Zee Music South",
            "Think Music India",
            "Think Music Telugu",
            "Lahari Music",
            "Lahari Music | T-Series",
            "Tips Official",
            "Tips Telugu",
            "Sun Pictures",
            "Sun TV",
            "YRF",
            "Muzik247",
            "Divo Music",
            "U1 Records",
            "Speed Records",
            "Anand Audio",
        ]
        for upl in official_uploaders:
            self.assertTrue(
                is_official_music_source(upl),
                f"Expected '{upl}' to be identified as an official music source",
            )

    def test_youtube_oac_topic_detection(self):
        """YouTube Official Artist Channels ending in ' - Topic' must be recognized."""
        oac_channels = [
            "Anirudh Ravichander - Topic",
            "A.R. Rahman - Topic",
            "Arijit Singh - Topic",
            "Sid Sriram - Topic",
            "Shreya Ghoshal - Topic",
            "Devi Sri Prasad - Topic",
            "Thaman S - Topic",
            "Taylor Swift - Topic",
        ]
        for ch in oac_channels:
            self.assertTrue(
                is_official_music_source(ch),
                f"Expected OAC '{ch}' to be recognized as official",
            )

    def test_celebrity_artists_detection(self):
        """Celebrity singers and composers must be recognized as official music sources."""
        celebrities = [
            "Anirudh Ravichander",
            "Anirudh",
            "A.R. Rahman",
            "Devi Sri Prasad",
            "Thaman S",
            "Santhosh Narayanan",
            "Yuvan Shankar Raja",
            "Arijit Singh",
            "Sid Sriram",
            "Shreya Ghoshal",
            "S.P. Balasubrahmanyam",
            "Sonu Nigam",
            "Diljit Dosanjh",
            "Taylor Swift",
            "Ed Sheeran",
        ]
        for artist in celebrities:
            self.assertTrue(
                is_official_music_source(artist),
                f"Expected celebrity artist '{artist}' to be recognized as official",
            )

    def test_unofficial_channels_rejected(self):
        """Unofficial fan edit channels, status makers, and bootlegs must be detected as unofficial."""
        unofficial_channels = [
            "Vxin Editz",
            "7 NIGHT VIBE",
            "Shadow Edits",
            "SK Dance Floor",
            "bittu_playlist",
            "V-Mix Labs",
            "Musical Haven",
            "Telugu Status World",
            "Whatsapp Status Maker",
            "Slowed Reverb Beats",
            "Bass Boosted King",
            "Lofi Chill Zone",
            "Dance Floor Choreography",
            "Infinitum Movies",
            "Film Talkies Official",
            "Movie Climax Scenes",
        ]
        for ch in unofficial_channels:
            self.assertTrue(
                is_unofficial_source(ch),
                f"Expected '{ch}' to be identified as an unofficial source",
            )
            self.assertFalse(
                is_official_music_source(ch),
                f"Expected '{ch}' NOT to be recognized as an official music source",
            )

    def test_duration_thresholds(self):
        """Single songs must have duration <= MAX_SONG_DURATION (360s) and >= MIN_SONG_DURATION (45s)."""
        self.assertEqual(MAX_SONG_DURATION, 360)
        self.assertEqual(MIN_SONG_DURATION, 45)

        # Standard songs (2-5 minutes) classified as 'song'
        self.assertEqual(classify_track_type("Chuttamalle - Devara", 217), "song")
        self.assertEqual(classify_track_type("Hukum - Jailer", 207), "song")
        self.assertEqual(classify_track_type("Naatu Naatu - RRR", 275), "song")

        # Over 6 minutes (360s) classified as 'playlist'
        self.assertEqual(classify_track_type("Some Long Track", 361), "playlist")
        self.assertEqual(classify_track_type("Full Song Compilation", 1200), "playlist")
        self.assertEqual(classify_track_type("30 Minutes Telugu Hits", 1800), "playlist")

    def test_compilation_and_movie_titles_rejected(self):
        """Compilations, jukeboxes, full albums, and movies must be detected and classified as playlist."""
        compilation_titles = [
            "Top 30 Telugu Hits - Audio Playlist | Part-1",
            "Anirudh Blockbuster Hits | Telugu Songs | JUKEBOX",
            "Power Packed Hits | Superhit Songs from Jailer 2, Coolie , Jailer , Beast",
            "90's Telugu Melody Songs | Nonstop Melody Mix",
            "Chuttamalle Vachesindi | Full Movie | 1080p FHD",
            "Chuttamalle (Slowed + Reverb) Shilpa Rao",
            "Naatu Naatu 8D Audio Bass Boosted",
            "Devara All Songs In One Jukebox",
            "Best of AR Rahman Super Hits Collection",
            "Evergreen Telugu Hits Vol. 1",
        ]
        for title in compilation_titles:
            self.assertTrue(
                is_compilation_or_junk(title),
                f"Expected '{title}' to be detected as compilation or junk",
            )
            self.assertEqual(
                classify_track_type(title, 200),
                "playlist",
                f"Expected '{title}' to be classified as playlist",
            )

    def test_is_valid_single_song_validation(self):
        """Test the end-to-end single song validator for queuing and radio recommendations."""
        # 1. Valid official song
        valid_track = {
            "video_id": "abc12345678",
            "title": "Chuttamalle - Devara",
            "artist": "T-Series Telugu",
            "channel": "T-Series Telugu",
            "duration": 217,
            "track_type": "song",
        }
        self.assertTrue(is_valid_single_song(valid_track))

        # 2. Too long (7-minute track)
        too_long = dict(valid_track, duration=420)
        self.assertFalse(is_valid_single_song(too_long))

        # 3. 30-minute compilation
        compilation_duration = dict(valid_track, duration=1850)
        self.assertFalse(is_valid_single_song(compilation_duration))

        # 4. Too short (< 45s teaser/short)
        too_short = dict(valid_track, duration=25)
        self.assertFalse(is_valid_single_song(too_short))

        # 5. Jukebox title even if duration looks moderate
        jukebox = dict(valid_track, title="Top 10 Telugu Jukebox Songs")
        self.assertFalse(is_valid_single_song(jukebox))

        # 6. Unofficial fan edit channel
        unofficial_track = dict(valid_track, artist="Vxin Editz", channel="Vxin Editz")
        self.assertFalse(is_valid_single_song(unofficial_track))

        # 7. Slowed & Reverb audio
        slowed_track = dict(valid_track, title="Chuttamalle (Slowed + Reverb)")
        self.assertFalse(is_valid_single_song(slowed_track))

        # 8. Full movie
        movie_track = dict(valid_track, title="Chuttamalle Vachesindi Full Movie", duration=18000)
        self.assertFalse(is_valid_single_song(movie_track))

    def test_official_scoring_priority(self):
        """Official releases from recognized channels must score higher than unknown uploads."""
        official_track = {
            "video_id": "off1",
            "title": "Hukum Lyric Video - Jailer",
            "artist": "Sun TV",
            "channel": "Sun TV",
            "duration": 207,
        }
        unknown_track = {
            "video_id": "unk1",
            "title": "Hukum Song Audio",
            "artist": "RandomUploader123",
            "channel": "RandomUploader123",
            "duration": 207,
        }
        score_official = compute_track_quality_score(official_track, query="hukum")
        score_unknown = compute_track_quality_score(unknown_track, query="hukum")
        self.assertGreater(score_official, score_unknown)


if __name__ == "__main__":
    unittest.main()

