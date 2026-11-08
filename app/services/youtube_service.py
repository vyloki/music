"""
Wave - YouTube Service
Search YouTube for songs and extract audio metadata & stream URLs using yt-dlp.
"""

import yt_dlp
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
import re
import json

from app.database import database
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)

# Dedicated bounded thread pool for yt-dlp worker threads
_ytdlp_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="ytdlp_worker")

# Duration thresholds (in seconds)
# Typical individual songs are between 90s and 300s (under 5 minutes).
# Hard ceiling: 360s (6 minutes). Anything > 360s is considered a playlist/compilation.
MAX_SONG_DURATION = 360
MIN_SONG_DURATION = 45
IDEAL_SONG_DURATION_MAX = 300

# Verified Major Record Labels & Production Studios
OFFICIAL_RECORD_LABELS = [
    # T-Series (National & Regional)
    "t-series", "tseries", "t series", "t-series telugu", "t-series tamil",
    "t-series kannada", "t-series malayalam", "t-series apna punjab", "t-series bhakti sagar",
    "t-series bangla", "t-series pop chartbusters", "t-series regional", "t-series stage",
    # Aditya Music
    "aditya music", "adityamusic", "aditya movies", "aditya devotional",
    "aditya music telugu", "aditya music tamil",
    # Saregama (National & Regional)
    "saregama", "saregama music", "saregama telugu", "saregama tamil", "saregama south",
    "saregama malayalam", "saregama kannada", "saregama hum bhojpuri", "saregama bengali",
    "saregama classical", "saregama punjabi", "saregama ghazal",
    # Sony Music
    "sony music", "sonymusic", "sony music south", "sonymusicsouthvevo", "sony music india",
    "sonymusicindiavevo", "sony music entertainment",
    # Zee Music
    "zee music", "zeemusic", "zee music company", "zee music south", "zee music telugu",
    "zee music tamil", "zee music kannada", "zee music bhojpuri", "zee music classics",
    # Think Music
    "think music", "think music india", "think music telugu", "think music tamil",
    "think music malayalam", "think music kannada",
    # Lahari Music
    "lahari music", "lahari", "lahari music | t-series", "lahari telugu", "lahari tamil", "lahari kannada",
    # Tips
    "tips official", "tips telugu", "tips tamil", "tips industries", "tips punjabi",
    "tips bhojpuri", "tips music", "tips films",
    # Sun Pictures / Network
    "sun pictures", "sun tv", "sun music", "sun nxt",
    # YRF & Eros
    "yrf", "yash raj films", "yrf music", "eros now", "eros now music",
    # Malayalam / Tamil / Kannada / Punjabi specialists
    "muzik247", "divo music", "divo movies", "divo", "u1 records", "u1 music",
    "speed records", "white hill music", "saga hits", "saga music", "geet mp3", "jass records",
    "anand audio", "jhankar music", "a2 music", "ashwini recording company",
    "times music", "junglee music", "venus", "venus worldwide",
    # Global Majors & VEVO
    "universal music", "warner music", "warner records", "vevo", "columbia records",
    "atlantic records", "interscope", "republic records", "def jam", "rca records",
    # Regional film production houses releasing official soundtracks
    "mango music", "madhura audio", "madhura music", "svf music", "svf", "amara muzik",
    "satyam videos", "satyam audios", "manorama music", "goodwill entertainments",
    "behindwoods", "behindwoods air", "kvn productions", "kvn", "mythri movie makers",
    "geetha arts", "sri venkateswara creations", "svc", "hombale films",
    "vyjayanthi network", "vyjayanthi movies", "lyca productions", "red giant movies",
    "dharma productions", "nadiadwala grandson",
]

# Verified Celebrity Artists, Music Directors & Professional Singers
OFFICIAL_CELEBRITY_ARTISTS = [
    # Top Composers & Music Directors
    "anirudh", "anirudh ravichander", "a.r. rahman", "ar rahman", "a r rahman",
    "devi sri prasad", "dsp", "thaman s", "s. thaman", "thaman", "santhosh narayanan",
    "harris jayaraj", "yuvan shankar raja", "ilaiyaraaja", "ilayaraja", "m.m. keeravaani",
    "m m keeravaani", "keeravaani", "m m kreem", "g.v. prakash", "gv prakash",
    "g v prakash kumar", "d. imman", "d imman", "hiphop tamizha", "sushin shyam",
    "hesham abdul wahab", "sam c.s.", "sam cs", "mickey j meyer", "mickey j. meyer",
    "vivek-mervin", "vivek mervin", "vidyasagar", "sachin-jigar", "sachin jigar",
    "pritam", "amit trivedi", "vishal-shekhar", "vishal shekhar", "shankar-ehsaan-loy",
    "ajay-atul", "mithoon", "amaal mallik", "tanishk bagchi", "bheems ceciroleo",
    "bheems cecirolio", "bheems", "chaitan bharadwaj", "sai abhyankkar", "radhan",
    # Top Celebrity Singers
    "arijit singh", "sid sriram", "shreya ghoshal", "s.p. balasubrahmanyam", "spb",
    "s p balasubrahmanyam", "k.j. yesudas", "kj yesudas", "k.s. chithra", "ks chithra",
    "s. janaki", "s janaki", "hariharan", "shankar mahadevan", "sonu nigam",
    "shaan", "mohit chauhan", "armaan malik", "vishal mishra", "darshan raval",
    "jubin nautiyal", "atif aslam", "neha kakkar", "diljit dosanjh", "badshah",
    "guru randhawa", "ap dhillon", "karan aujla", "pradeep kumar", "anurag kulkarni",
    "ram miriyala", "rahul sipligunj", "mangli", "jasleen royal", "jonita gandhi",
    "sunidhi chauhan", "chinmayi", "shakthisree gopalan", "dhee", "andrea jeremiah",
    "vijay prakash", "karthik", "unni menon", "sujatha mohan", "sujatha", "mano",
    "swarnalatha", "haricharan", "naresh iyer", "lucky ali", "kk", "udit narayan",
    "kumar sanu", "alka yagnik", "kavita krishnamurthy", "lata mangeshkar",
    "mohammed rafi", "kishore kumar", "asha bhosle", "mukesh",
    # Global Icons
    "taylor swift", "ed sheeran", "the weeknd", "bruno mars", "dua lipa", "billie eilish",
    "justin bieber", "adele", "drake", "coldplay", "imagine dragons", "eminem",
    "post malone", "charlie puth", "shawn mendes", "alan walker", "avicii",
    "rihanna", "beyonce", "katy perry", "maroon 5", "selena gomez", "david guetta", "marshmello"
]

# Unofficial channel indicators to reject
UNOFFICIAL_CHANNELS = [
    "editz", "edits", "editor", "status", "whatsapp", "slowed", "reverb", "nightcore",
    "bass boosted", "bassboosted", "8d audio", "3d audio", "fan club", "fanclub",
    "fan made", "fan page", "dance floor", "dance cover", "choreography", "talkies",
    "movies", "cinema", "infinitum", "filmy", "film review", "reaction", "reviews",
    "public talk", "vlog", "vlogs", "troll", "comedy", "scenes", "clips", "shorts",
    "night vibe", "lofi zone", "lofi", "chill vibe", "vibes only", "song lyrics", "musical bytes",
    "musical haven", "jukebox world", "playlist hub", "playlist", "mix labs", "audio hub",
    "lyric video", "lyrics video"
]

# Patterns for compilation, jukebox, playlist, or movie videos
COMPILATION_PATTERNS = [
    r"\bjukebox\b", r"\baudio jukebox\b", r"\bvideo jukebox\b", r"\bmega jukebox\b",
    r"\ball songs\b", r"\bfull album\b", r"\bsuper hits collection\b", r"\bhit songs collection\b",
    r"\bsuperhit songs\b", r"\bsuper hit songs\b", r"\bpower packed hits\b", r"\bblockbuster hits\b",
    r"\btop\s*\d+\b", r"\bback to back\b", r"\bnon\s*stop\b", r"\bnonstop\b",
    r"\bcompilation\b", r"\bbest of\b", r"\baudio playlist\b", r"\bvideo playlist\b",
    r"\bevergreen hits\b", r"\bsuperhits collection\b", r"\bvol\.\s*\d+", r"\bvolume\s*\d+",
    r"\bpart[\s-]*\d+\s*full\b", r"\bpart[\s-]*\d+\b",
    r"\bfull movie\b", r"\bmovie scenes\b", r"\bfull hd movie\b", r"\bmovie online\b",
    r"\bpress meet\b", r"\bpublic talk\b", r"\bsuccess meet\b",
    r"\bslowed\s*(\+|\&)?\s*reverb\b", r"\bbass boosted\b", r"\b8d audio\b", r"\b3d audio\b",
    r"\bwhatsapp status\b", r"\bstatus video\b", r"\bdance cover\b", r"\breaction\b",
    r"\bfan made\b", r"\bedit audio\b", r"\b1 hour loop\b", r"\b10 hours\b",
    r"\b1 hour version\b", r"\bloop\b", r"\bdj remix\b", r"\bmashup\b"
]


def is_official_music_source(uploader: str, title: str = "") -> bool:
    """
    Check if the uploader is an official record label (e.g. T-Series, Aditya Music, Saregama),
    an Official Artist Channel ending with ' - Topic', a VEVO channel, or a verified celebrity singer/composer.
    """
    if not uploader:
        return False
    u = uploader.lower().strip()

    # 1. YouTube Official Artist Channel (OAC)
    if u.endswith(" - topic"):
        return True

    # 2. VEVO official channel
    if "vevo" in u:
        return True

    # 3. Major Record Labels & Production Studios
    if any(label in u for label in OFFICIAL_RECORD_LABELS):
        return True

    # 4. Celebrity Artists / Composers / Singers
    if any(artist in u for artist in OFFICIAL_CELEBRITY_ARTISTS):
        return True

    # 5. Title mentions official production with studio tag
    t = (title or "").lower()
    if any(label in t for label in ["t-series", "aditya music", "saregama", "sony music", "zee music"]):
        return True

    # 6. Channel has explicit official indicators and is not blacklisted
    if any(w in u for w in ["records", "studios", "pictures", "films", "entertainment"]):
        if not is_unofficial_source(uploader):
            return True

    return False


def is_unofficial_source(uploader: str) -> bool:
    """
    Check if uploader is an amateur/fan-made channel (editz, status, slowed, fanclub, etc.).
    """
    if not uploader:
        return False
    u = uploader.lower().strip()

    # Don't flag official labels even if they have "music" or "movies" (e.g. Aditya Movies)
    if any(label in u for label in OFFICIAL_RECORD_LABELS):
        return False
    if u.endswith(" - topic") or "vevo" in u:
        return False

    return any(pattern in u for pattern in UNOFFICIAL_CHANNELS)


def is_compilation_or_junk(title: str, duration: int = 0) -> bool:
    """
    Check if title or duration indicates a compilation, jukebox, full album, movie, or fan-modified audio.
    """
    if duration > MAX_SONG_DURATION:
        return True
    t = (title or "").lower()
    for p in COMPILATION_PATTERNS:
        if re.search(p, t):
            return True
    return False


def is_valid_single_song(track: dict) -> bool:
    """
    Validates that a track is a genuine single song:
    - Duration between MIN_SONG_DURATION (45s) and MAX_SONG_DURATION (360s, or 0 if unprobed)
    - Not a compilation, jukebox, full album, or movie
    - Not from an unofficial channel (editz, status, slowed, fan made, etc.)
    - track_type is 'song' or 'bgm' (not 'playlist')
    """
    if not track or not isinstance(track, dict):
        return False
    dur = int(track.get("duration") or 0)
    if dur > MAX_SONG_DURATION:
        return False
    if 0 < dur < MIN_SONG_DURATION:
        return False
    title = track.get("title") or track.get("track_name") or ""
    if is_compilation_or_junk(title, dur):
        return False
    uploader = track.get("artist") or track.get("uploader") or track.get("channel") or ""
    if is_unofficial_source(uploader):
        return False
    if track.get("track_type") == "playlist":
        return False
    return True


def compute_track_quality_score(track: dict, query: str = "") -> float:
    """
    Computes ranking score for YouTube search results:
    - Official record labels / OAC / celebrity artists: +100.0
    - Verified / official music keywords in uploader: +40.0
    - Ideal song duration (120s - 300s): +30.0
    - Clean duration (45s - 360s): +15.0
    - Unofficial channel: -150.0
    - Long duration (> 360s): -300.0
    """
    score = 0.0
    dur = int(track.get("duration") or 0)
    upl = track.get("artist") or track.get("uploader") or track.get("channel") or ""
    title = track.get("title") or track.get("track_name") or ""

    if is_official_music_source(upl, title):
        score += 100.0
    elif any(w in upl.lower() for w in ["music", "records", "audio", "studios"]):
        score += 35.0

    if is_unofficial_source(upl):
        score -= 150.0

    if dur > MAX_SONG_DURATION:
        score -= 300.0
    elif 90 <= dur <= IDEAL_SONG_DURATION_MAX:
        score += 30.0
    elif MIN_SONG_DURATION <= dur <= MAX_SONG_DURATION:
        score += 15.0

    # Query matching in title
    if query:
        q_words = [w.lower() for w in query.split() if len(w) > 2]
        title_lower = title.lower()
        matched = sum(1 for w in q_words if w in title_lower)
        score += matched * 10.0

    return score

# yt-dlp options for fast flat search
SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "skip_download": True,
    "ignoreerrors": True,
    "no_color": True,
    "socket_timeout": 15,
}

# yt-dlp options for stream URL extraction
STREAM_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "format": "ba[acodec!=none]/bestaudio/ba/b/18/best",
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "ios", "mweb", "web"],
        }
    },
    "ignoreerrors": False,
    "no_color": True,
    "socket_timeout": 15,
}


def detect_language(raw_title: str, uploader: str, query: str = "") -> str:
    """Detect language of a song from title, uploader, or query."""
    combined = f"{raw_title} {uploader} {query}".lower()
    lang_map = {
        "telugu": "Telugu", "tamil": "Tamil", "hindi": "Hindi",
        "malayalam": "Malayalam", "kannada": "Kannada", "punjabi": "Punjabi",
        "english": "English", "bengali": "Bengali", "bangla": "Bengali",
        "marathi": "Marathi", "gujarati": "Gujarati", "bhojpuri": "Bhojpuri",
        "korean": "Korean", "spanish": "Spanish", "japanese": "Japanese"
    }
    for k, v in lang_map.items():
        if re.search(r"\b" + k + r"\b", combined):
            return v

    upl_lower = uploader.lower()
    if any(k in upl_lower for k in ["think music telugu", "aditya music", "mango music", "lahari", "saregama telugu", "zee music telugu", "madhura", "t-series telugu"]):
        return "Telugu"
    if any(k in upl_lower for k in ["think music india", "think music tamil", "sun pictures", "divo", "u1 records", "sony music south", "saregama tamil", "behindwoods", "sony music tamil", "zee music tamil", "tips tamil"]):
        return "Tamil"
    if any(k in upl_lower for k in ["t-series", "zee music", "yrf", "sony music india", "tips official", "eros now", "saregama music"]):
        return "Hindi"
    if any(k in upl_lower for k in ["muzik247", "123musix", "goodwill", "saregama malayalam"]):
        return "Malayalam"
    if any(k in upl_lower for k in ["anand audio", "jhankar", "a2 music"]):
        return "Kannada"
    if any(k in upl_lower for k in ["speed records", "apna punjab", "geet mp3"]):
        return "Punjabi"

    return ""


def _clean_part(text: str) -> str:
    """Clean video noise tags from an individual title segment."""
    s = text
    noise_patterns = [
        # Official tags
        r'\(Official\s*(Music\s*)?Video\)',
        r'\[Official\s*(Music\s*)?Video\]',
        r'\(Official\s*Audio\)',
        r'\[Official\s*Audio\]',
        r'\(Official\s*Song\)',
        r'\[Official\s*Song\]',
        r'\(Official\s*Lyric\s*Video\)',
        r'\[Official\s*Lyric\s*Video\]',
        r'\(Official\)',
        r'\[Official\]',
        r'\(Lyric\s*Video\)',
        r'\[Lyric\s*Video\]',
        r'\(Lyrical\s*Video\)',
        r'\[Lyrical\s*Video\]',
        r'\bLyrical\s*Video\b',
        r'\bLyric\s*Video\b',
        r'\(Audio\)',
        r'\[Audio\]',
        r'\(Visualizer\)',
        r'\[Visualizer\]',
        r'\(Video\)',
        r'\[Video\]',
        r'4K\s*Ultra\s*HD\s*Video\s*Song',
        r'4K\s*Video\s*Song',
        r'4K\s*Full\s*Video',
        r'4K\s*Video',
        r'4K\s*Song',
        r'\b4K\b',
        r'\b8K\b',
        r'Full\s*HD\s*Video\s*Song',
        r'Full\s*HD\s*Video',
        r'\bFull\s*Video\s*Song\b',
        r'\bVideo\s*Song\b',
        r'\bFull\s*Song\b',
        r'\bFull\s*Video\b',
        r'\bHD\s*Video\b',
        r'\bHD\s*Song\b',
        r'\bHD\b',
        r'Official\s*Video',
        r'Official\s*Song',
        r'Music\s*Video',
        r'Promotional\s*Video',
        r'Promo\s*Video',
        r'Promo\s*Song',
        r'\(Unplugged\)',
        r'\[Unplugged\]',
        r'\bUnplugged\s*Version\b',
        r'\bUnplugged\b',
        r'\(Remastered\)',
        r'\[Remastered\]',
        r'\bRemastered\b',
        r'\(Movie\s*Version\)',
        r'\[Movie\s*Version\]',
        r'\bMovie\s*Version\b',
        r'\(Film\s*Version\)',
        r'\[Film\s*Version\]',
        r'\bFilm\s*Version\b',
        r'\(8D\s*Audio\)',
        r'\[8D\s*Audio\]',
        r'\b8D\s*Audio\b',
        r'\(Bass\s*Boosted\)',
        r'\[Bass\s*Boosted\]',
        r'\bBass\s*Boosted\b',
        r'\(Slowed\s*\+?\s*Reverb\)',
        r'\[Slowed\s*\+?\s*Reverb\]',
        r'\bSlowed\s*\+?\s*Reverb\b',
        r'\(Slowed\)',
        r'\[Slowed\]',
        r'\(Reverb\)',
        r'\[Reverb\]',
        r'\(Live\)',
        r'\[Live\]',
        r'\bLive\s*Version\b',
        r'\(Acoustic\)',
        r'\[Acoustic\]',
        r'\bAcoustic\s*Version\b',
        r'\(Cover\)',
        r'\[Cover\]',
        r'\bCover\s*Version\b',
        r'\(Lyrics\)',
        r'\[Lyrics\]',
        r'\(With\s*Lyrics\)',
        r'\[With\s*Lyrics\]',
        r'\(Full\)',
        r'\[Full\]',
        r'\(Audio\s*Jukebox\)',
        r'\[Audio\s*Jukebox\]',
    ]
    for p in noise_patterns:
        s = re.sub(p, "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\(.*?Official.*?\)", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\[.*?Official.*?\]", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^[\s|\-:]+|[\s|\-:]+$", "", s).strip()
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _parse_track_metadata(raw_title: str, uploader: str, query: str = "") -> dict:
    """
    Parse Spotify/Apple Music-style metadata:
    - Clean Title
    - Movie Name
    - Language
    - Artist
    - Subtitle (e.g. 'Dude • Telugu')
    """
    language = detect_language(raw_title, uploader, query)

    # Check for (From "Movie")
    from_match = re.search(r"""(?:(?:\(|\[)?(?:From|from)\s*["\x27]([^"\x27]+)["\x27](?:\)|\])?)""", raw_title, re.IGNORECASE)
    movie_from_tag = from_match.group(1).strip() if from_match else ""

    cleaned_full = raw_title
    if from_match:
        cleaned_full = raw_title[:from_match.start()] + raw_title[from_match.end():]

    delims = ["||", "|", " - ", " – ", " — "]
    parts = []
    for d in delims:
        if d in cleaned_full:
            parts = [_clean_part(p) for p in cleaned_full.split(d) if p.strip()]
            break
    if not parts:
        parts = [_clean_part(cleaned_full)]

    parts = [p for p in parts if p]

    title = parts[0] if parts else raw_title
    title = re.sub(r"\((?:Telugu|Tamil|Hindi|Malayalam|Kannada|Punjabi|English)\)", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\[(?:Telugu|Tamil|Hindi|Malayalam|Kannada|Punjabi|English)\]", "", title, flags=re.IGNORECASE).strip()

    movie = movie_from_tag
    artist = uploader or "Unknown Artist"
    is_artist_track = False

    # Check if format is "Artist - Song" (e.g. "Ed Sheeran - Shape of You")
    if " - " in cleaned_full and not movie_from_tag and len(parts) >= 2:
        if uploader.lower() in parts[0].lower() or parts[0].lower() in uploader.lower():
            artist = parts[0]
            title = parts[1]
            is_artist_track = True

    if not movie and not is_artist_track and len(parts) > 1:
        candidate_movie = parts[1]
        candidate_movie = re.sub(r"\b(?:Telugu|Tamil|Hindi|Malayalam|Kannada|Punjabi|English)\b", "", candidate_movie, flags=re.IGNORECASE).strip()
        candidate_movie = re.sub(r"^[\s|\-:]+|[\s|\-:]+$", "", candidate_movie).strip()
        if candidate_movie and not any(kw in candidate_movie.lower() for kw in ["t-series", "music", "channel", "records", "video", "subscribe", "audio"]):
            movie = candidate_movie
            if len(parts) > 2:
                candidate_artist = parts[2]
                if candidate_artist and not any(kw in candidate_artist.lower() for kw in ["t-series", "channel", "video", "subscribe"]):
                    artist = candidate_artist

    if not movie and not is_artist_track and query:
        q_words = [w for w in query.split() if w.lower() not in ["songs", "song", "video", "audio", "telugu", "tamil", "hindi", "mp3", "all", "best", "hits"]]
        if q_words:
            movie = " ".join(w.capitalize() for w in q_words)

    if artist.endswith(" - Topic"):
        artist = artist.replace(" - Topic", "")
    if "VEVO" in artist:
        artist = re.sub(r"VEVO", "", artist, flags=re.IGNORECASE).strip()

    if movie:
        subtitle = f"{movie} • {language}" if language else movie
    else:
        subtitle = f"{artist} • {language}" if language else artist

    return {
        "title": title or raw_title,
        "movie": movie,
        "language": language,
        "artist": artist,
        "subtitle": subtitle,
    }


def _classify_track_type(raw_title: str, duration: int) -> str:
    """
    Classify a track as 'song', 'bgm', or 'playlist' based on title keywords and duration.
    - playlist: duration > MAX_SONG_DURATION (360s / 6 min), OR title has compilation/jukebox/playlist keywords
    - bgm: title has bgm/background/instrumental/theme keywords AND duration <= MAX_SONG_DURATION
    - song: everything else (individual songs under 6 minutes)
    """
    title_lower = raw_title.lower()

    if duration > MAX_SONG_DURATION or is_compilation_or_junk(raw_title, duration):
        return 'playlist'

    # BGM / instrumental indicators
    bgm_keywords = [
        'bgm', 'background music', 'background score', 'instrumental',
        'theme music', 'ost', 'score', 'ringtone', 'background',
    ]
    if any(kw in title_lower for kw in bgm_keywords):
        return 'bgm'

    return 'song'


# Public alias
classify_track_type = _classify_track_type



def _extract_track_from_entry(entry: dict, query: str = "") -> Optional[dict]:
    """Extract standard track dictionary from a flat or detailed yt-dlp entry."""
    if not entry:
        return None

    video_id = entry.get("id") or entry.get("url")
    if not video_id:
        return None

    # Strip full URL if id is a url
    if "youtube.com" in video_id or "youtu.be" in video_id:
        match = re.search(r'(?:v=|/)([0-9A-Za-z_-]{11})', video_id)
        if match:
            video_id = match.group(1)
        else:
            return None

    raw_title = entry.get("title") or "Unknown Song"
    uploader = entry.get("uploader") or entry.get("channel") or ""

    meta = _parse_track_metadata(raw_title, uploader, query)

    # Get thumbnail
    thumbnail = ""
    thumbnails = entry.get("thumbnails", [])
    if thumbnails and isinstance(thumbnails, list):
        # Grab the highest resolution or last thumbnail
        for t in reversed(thumbnails):
            if isinstance(t, dict) and t.get("url"):
                thumbnail = t["url"]
                break

    if not thumbnail:
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    duration = int(entry.get("duration") or 0)
    track_type = _classify_track_type(raw_title, duration)
    official = is_official_music_source(uploader or meta["artist"], raw_title)

    return {
        "video_id": video_id,
        "title": raw_title,
        "track_name": meta["title"],
        "movie": meta["movie"],
        "language": meta["language"],
        "artist": meta["artist"],
        "subtitle": meta["subtitle"],
        "album": entry.get("album") or meta["movie"] or "",
        "duration": duration,
        "thumbnail": thumbnail,
        "view_count": entry.get("view_count") or 0,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "source": "youtube",
        "track_type": track_type,
        "is_official": official,
        "channel": uploader,
    }


async def search_youtube(
    query: str,
    max_results: int = 20,
    filter_mode: str = "song",
) -> List[dict]:
    """
    Search YouTube for songs matching the query.
    Enforces strict filtering:
      - Song duration <= MAX_SONG_DURATION (360s / 6 mins) and >= MIN_SONG_DURATION (45s).
      - Rejects unofficial fan channels (editz, status, slowed, fan made, etc.).
      - Rejects compilations, jukeboxes, full albums, and movies.
      - Prioritizes official record labels (T-Series, Aditya Music, Saregama, Sony, Zee, Think Music)
        and verified celebrity artists/singers (Anirudh, AR Rahman, Sid Sriram, Arijit Singh, etc.).
    Returns a list of track info dictionaries.
    """
    def _search():
        # Fetch up to 2x results to allow thorough filtering of unofficial content
        fetch_count = max(max_results * 2, 25)
        search_query = f"ytsearch{fetch_count}:{query}"
        candidates = []

        try:
            with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if info and "entries" in info:
                    for entry in info["entries"]:
                        track = _extract_track_from_entry(entry, query=query)
                        if track and track["video_id"]:
                            candidates.append(track)
        except Exception as e:
            logger.error(f"YouTube search error for '{query}': {e}")
            return []

        if not candidates:
            return []

        # If user explicitly searches for compilation/jukebox/album, keep playlist entries
        q_lower = query.lower()
        wants_compilation = any(k in q_lower for k in ["jukebox", "all songs", "full album", "playlist", "compilation"])

        if filter_mode == "song" and not wants_compilation:
            filtered = []
            for t in candidates:
                dur = t.get("duration", 0)
                upl = t.get("channel") or t.get("artist") or ""
                title = t.get("title") or t.get("track_name") or ""

                # Discard tracks over 6 minutes (360s) or under 45s (if duration is known)
                if dur > MAX_SONG_DURATION or (0 < dur < MIN_SONG_DURATION):
                    continue

                # Discard compilation, jukebox, or movie titles
                if is_compilation_or_junk(title, dur):
                    continue

                # Discard unofficial channels (editz, status, slowed, etc.)
                if is_unofficial_source(upl):
                    continue

                # Discard classified playlists
                if t.get("track_type") == "playlist":
                    continue

                filtered.append(t)

            # Sort filtered tracks by quality score (official channels first, ideal duration next)
            filtered.sort(key=lambda t: compute_track_quality_score(t, query), reverse=True)

            # If strict filtering left fewer than requested, salvage clean candidates with dur <= 360s
            if len(filtered) < max_results:
                seen_ids = set(t["video_id"] for t in filtered)
                for t in candidates:
                    vid = t.get("video_id")
                    dur = t.get("duration", 0)
                    if vid and vid not in seen_ids:
                        if dur <= MAX_SONG_DURATION and not is_compilation_or_junk(t.get("title", ""), dur):
                            if not is_unofficial_source(t.get("channel", "")):
                                filtered.append(t)
                                seen_ids.add(vid)
                                if len(filtered) >= max_results:
                                    break

            return filtered[:max_results]

        # For "all" or explicit album/compilation queries, rank official single songs first, keep others marked
        candidates.sort(key=lambda t: compute_track_quality_score(t, query), reverse=True)
        return candidates[:max_results]

    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(_ytdlp_executor, _search)

    logger.info(f"🔍 YouTube search '{query}' (mode={filter_mode}): {len(results)} clean results")
    return results


async def get_video_info(video_id: str) -> Optional[dict]:
    """
    Get detailed info for a specific YouTube video.
    Checks MongoDB song_cache first before invoking yt-dlp.
    """
    db = database.db
    if db is not None:
        try:
            cached = await db.song_cache.find_one({"video_id": video_id})
            if not cached:
                cached = await db.song_cache.find_one({"_id": video_id})

            if cached:
                cached_at = cached.get("cached_at")
                is_recent = True
                if cached_at:
                    if isinstance(cached_at, str):
                        try:
                            cached_at = datetime.fromisoformat(cached_at)
                        except Exception:
                            cached_at = None
                    if isinstance(cached_at, datetime):
                        if cached_at.tzinfo is None:
                            cached_at = cached_at.replace(tzinfo=timezone.utc)
                        # Retain cache for 7 days
                        if (datetime.now(timezone.utc) - cached_at).total_seconds() > 7 * 86400:
                            is_recent = False

                if is_recent:
                    cached.pop("_id", None)
                    cached["video_id"] = video_id
                    return {
                        "video_id": video_id,
                        "title": cached.get("title") or cached.get("track_name") or "Unknown Song",
                        "track_name": cached.get("track_name") or cached.get("title") or "Unknown Song",
                        "movie": cached.get("movie", ""),
                        "language": cached.get("language", ""),
                        "artist": cached.get("artist", "Unknown Artist"),
                        "subtitle": cached.get("subtitle", ""),
                        "album": cached.get("album") or cached.get("movie") or "",
                        "duration": int(cached.get("duration") or 0),
                        "thumbnail": cached.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                        "view_count": cached.get("view_count") or 0,
                        "webpage_url": cached.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
                        "source": cached.get("source") or "youtube",
                        "track_type": cached.get("track_type") or "song",
                        "is_official": cached.get("is_official", False),
                        "channel": cached.get("channel", ""),
                    }
        except Exception as e:
            logger.debug(f"Song cache lookup skipped for {video_id}: {e}")

    def _get_info():
        url = f"https://www.youtube.com/watch?v={video_id}"
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return _extract_track_from_entry(info)
        except Exception as e:
            logger.error(f"Video info error for {video_id}: {e}")
        return None

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_ytdlp_executor, _get_info)

    if result and db is not None:
        try:
            doc_to_cache = {k: v for k, v in result.items() if k != "_id"}
            doc_to_cache["video_id"] = video_id
            doc_to_cache["cached_at"] = datetime.now(timezone.utc)
            await db.song_cache.update_one(
                {"video_id": video_id},
                {"$set": doc_to_cache, "$setOnInsert": {"_id": video_id}},
                upsert=True,
            )
        except Exception as e:
            logger.debug(f"Failed to update song_cache for {video_id}: {e}")

    return result


async def get_stream_url(video_id: str) -> Optional[dict]:
    """
    Extract the direct audio stream URL for a YouTube video using Android/iOS/Web clients.
    """
    def _extract():
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            with yt_dlp.YoutubeDL(STREAM_OPTS) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    stream_url = info.get("url")
                    if stream_url:
                        return {
                            "url": stream_url,
                            "format": info.get("format", ""),
                            "ext": info.get("ext", "mp4"),
                            "filesize": info.get("filesize"),
                            "duration": int(info.get("duration") or 0),
                            "title": info.get("title", ""),
                            "expires_at": datetime.now(timezone.utc),
                        }
        except Exception as e:
            logger.error(f"Stream extraction error for {video_id}: {e}")
        return None

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_ytdlp_executor, _extract)

    if result:
        logger.info(f"🎶 Stream URL extracted for {video_id} ({result.get('ext')})")
    else:
        logger.warning(f"⚠️ Failed to extract stream for {video_id}")

    return result


async def get_search_suggestions(query: str) -> List[str]:
    """Get clean, music-focused YouTube search autocomplete suggestions (Spotify style)."""
    blocked_terms = [
        "trailer", "teaser", "review", "reaction", "full movie", "movie review",
        "movie scenes", "scene", "scenes", "comedy", "interview", "press meet",
        "box office", "public talk", "status", "whatsapp", "roast", "making",
        "news", "vlog", "shorts", "short", "spoiler", "ott", "glimpse", "climax",
        "story", "budget", "collection", "troll", "episode", "episodes", "part 1 full",
        "full hd movie", "movie download", "movie online", "cinema", "film review",
        "movie telugu full", "movie tamil full", "movie hindi full", "full film"
    ]

    try:
        url = "https://suggestqueries-clients6.youtube.com/complete/search"
        params = {
            "client": "youtube",
            "q": query,
            "ds": "yt",
        }
        client = get_http_client()
        resp = await client.get(url, params=params, timeout=4.0)
        if resp.status_code == 200:
            text = resp.text
            start = text.index("(") + 1
            end = text.rindex(")")
            data = json.loads(text[start:end])
            if data and len(data) > 1 and isinstance(data[1], list):
                raw_suggestions = [item[0] for item in data[1] if item and isinstance(item, list)]
                cleaned_list = []
                seen = set()

                for s in raw_suggestions:
                    if not isinstance(s, str):
                        continue
                    s_clean = s.strip()
                    s_lower = s_clean.lower()

                    # Skip blocked non-music terms
                    if any(b in s_lower for b in blocked_terms):
                        continue

                    # If contains "movie" without music terms, skip
                    if "movie" in s_lower:
                        if not any(k in s_lower for k in ["song", "bgm", "music", "audio", "album", "track", "soundtrack"]):
                            continue
                        s_clean = re.sub(r"\bmovie\s+songs?\b", "songs", s_clean, flags=re.IGNORECASE)
                        s_clean = re.sub(r"\bmovie\b", "", s_clean, flags=re.IGNORECASE)

                    # Clean "video song/songs" -> "songs"
                    s_clean = re.sub(r"\bvideo\s+songs?\b", "songs", s_clean, flags=re.IGNORECASE)
                    # Clean noise tags like 4k, hd, full video, official video, etc.
                    s_clean = re.sub(r"\b(4k|8k|hd|full\s*video|official\s*video|lyrical\s*video|lyrics|official)\b", "", s_clean, flags=re.IGNORECASE)
                    s_clean = re.sub(r"\s{2,}", " ", s_clean).strip()

                    if s_clean and s_clean.lower() not in seen:
                        seen.add(s_clean.lower())
                        cleaned_list.append(s_clean)

                return cleaned_list[:8]
    except Exception as e:
        logger.warning(f"Suggestions error for '{query}': {e}")

    return []


# Backwards compatibility alias
get_youtube_suggestions = get_search_suggestions


async def get_related_videos(video_id: str, max_results: int = 10) -> List[dict]:
    """Get related/recommended tracks for a given video, strictly filtering for authentic single songs."""
    def _get_related():
        url = f"https://www.youtube.com/watch?v={video_id}"
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "ignoreerrors": True,
        }
        results = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    related = info.get("related_videos", []) or []
                    for entry in related:
                        track = _extract_track_from_entry(entry)
                        if not track or not track.get("video_id"):
                            continue
                        # Strictly enforce single-song & official standards
                        if not is_valid_single_song(track):
                            continue
                        track["source"] = "youtube_related"
                        results.append(track)
                        if len(results) >= max_results:
                            break
        except Exception as e:
            logger.warning(f"Related videos error for {video_id}: {e}")

        return results

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_ytdlp_executor, _get_related)


async def get_language_versions(
    track_name: str,
    movie: str = "",
    current_video_id: str = "",
) -> List[dict]:
    """
    Search YouTube for this song in multiple languages and return one best match per language.
    Uses asyncio.gather with Semaphore(3) to cap concurrent searches.
    Languages checked: Telugu, Tamil, Hindi, Malayalam, Kannada.
    """
    languages = ["Telugu", "Tamil", "Hindi", "Malayalam", "Kannada"]
    base_query = f"{track_name} {movie}".strip()
    sem = asyncio.Semaphore(3)

    async def _search_one_language(lang: str) -> Optional[dict]:
        async with sem:
            query = f"{base_query} {lang} song"
            try:
                results = await search_youtube(query, max_results=5)
                for r in results:
                    vid = r.get("video_id", "")
                    # Skip the current playing song's own video
                    if vid and vid != current_video_id:
                        detected_lang = r.get("language", "")
                        # Only return if language matches or is close
                        if not detected_lang or detected_lang.lower() == lang.lower():
                            r["language"] = lang  # Force the language we searched for
                            return r
            except Exception as e:
                logger.debug(f"Language version search failed for {lang}: {e}")
            return None

    # Fan out all language searches in parallel capped by semaphore
    tasks = [_search_one_language(lang) for lang in languages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    versions = []
    seen_ids = set()
    if current_video_id:
        seen_ids.add(current_video_id)

    for i, r in enumerate(results):
        if r and isinstance(r, dict):
            vid = r.get("video_id", "")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                versions.append({
                    "language": languages[i],
                    "video_id": vid,
                    "title": r.get("track_name") or r.get("title", ""),
                    "thumbnail": r.get("thumbnail", ""),
                    "artist": r.get("artist", ""),
                    "duration": r.get("duration", 0),
                    "movie": r.get("movie", ""),
                    "subtitle": r.get("subtitle", ""),
                })

    return versions


async def search_multi_language(
    query: str,
    languages: Optional[List[str]] = None,
    max_results: int = 5,
) -> Dict[str, List[dict]]:
    """
    Search YouTube across multiple languages concurrently with Semaphore(3) concurrency cap.
    """
    if languages is None:
        languages = ["Telugu", "Tamil", "Hindi", "Malayalam", "Kannada", "English"]

    sem = asyncio.Semaphore(3)

    async def _search_lang(lang: str) -> tuple[str, List[dict]]:
        async with sem:
            q = f"{query} {lang}".strip()
            try:
                res = await search_youtube(q, max_results=max_results)
                return lang, res
            except Exception as e:
                logger.debug(f"Multi-language search failed for {lang}: {e}")
                return lang, []

    tasks = [_search_lang(l) for l in languages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: Dict[str, List[dict]] = {}
    for r in results:
        if isinstance(r, tuple) and len(r) == 2:
            lang, tracks = r
            output[lang] = tracks
    return output


async def get_trending_multi_language(
    languages: Optional[List[str]] = None,
    max_results: int = 10,
) -> Dict[str, List[dict]]:
    """
    Fetch trending tracks across multiple languages concurrently with Semaphore(3) concurrency cap.
    """
    if languages is None:
        languages = ["Telugu", "Tamil", "Hindi", "English", "Malayalam", "Kannada", "Punjabi"]

    sem = asyncio.Semaphore(3)

    async def _fetch_trending_lang(lang: str) -> tuple[str, List[dict]]:
        async with sem:
            q = f"Top trending {lang} songs"
            try:
                res = await search_youtube(q, max_results=max_results)
                return lang, res
            except Exception as e:
                logger.debug(f"Trending multi-language fetch failed for {lang}: {e}")
                return lang, []

    tasks = [_fetch_trending_lang(l) for l in languages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: Dict[str, List[dict]] = {}
    for r in results:
        if isinstance(r, tuple) and len(r) == 2:
            lang, tracks = r
            output[lang] = tracks
    return output


class YouTubeService:
    """YouTube Service providing search, stream extraction, suggestion, and metadata operations."""

    search_youtube = staticmethod(search_youtube)
    get_video_info = staticmethod(get_video_info)
    get_stream_url = staticmethod(get_stream_url)
    get_search_suggestions = staticmethod(get_search_suggestions)
    get_youtube_suggestions = staticmethod(get_search_suggestions)
    get_related_videos = staticmethod(get_related_videos)
    get_language_versions = staticmethod(get_language_versions)
    search_multi_language = staticmethod(search_multi_language)
    get_trending_multi_language = staticmethod(get_trending_multi_language)
    is_official_music_source = staticmethod(is_official_music_source)
    is_unofficial_source = staticmethod(is_unofficial_source)
    is_compilation_or_junk = staticmethod(is_compilation_or_junk)
    is_valid_single_song = staticmethod(is_valid_single_song)
    classify_track_type = staticmethod(classify_track_type)
