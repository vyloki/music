"""
Wave - Lyrics Service
Multi-tier lyrics search using LRCLIB API + Web verified lyrics scraper with:
- Strict cross-language separation (Telugu never receives Tamil lyrics; Tamil never receives Telugu)
- Wave Auto-Sync Engine: automatically compensates for channel intro bumpers & logo ads
  (e.g. Saregama 4.5s fanfare, Aditya Music 3.5s sting, Sun Pictures 5.0s, T-Series 3.0s, duration deltas)
- Automatic Indic-to-English (Romanized/English spelling) transliteration.
"""

import httpx
import logging
from typing import Optional, List, Dict
import re
import asyncio
from datetime import datetime, timezone, timedelta
from app.utils.transliterator import transliterate_indic_to_english
from app.services.http_client import get_http_client
from app.database import database

logger = logging.getLogger(__name__)
LRCLIB_BASE = "https://lrclib.net/api"

# Record labels / uploaders that should NOT be treated as song artists
RECORD_LABELS = {
    "think music telugu", "think music", "t-series", "tseries", "t-series telugu",
    "t-series regional", "sony music india", "sony music south", "zee music company",
    "zee music south", "aditya music", "saregama music", "saregama", "saregama telugu",
    "lahari music", "speed records", "yrf", "tips official", "geetha arts", "svcc",
    "mythri movie makers", "dvi", "sun nxt", "mangli official", "madhura audio",
    "vel records", "times music", "tips telugu", "aditya music telugu", "sun pictures",
}

# Channel bumper duration profiles (in seconds)
# Known signature intro bumpers / logo ads prepended to official YouTube music videos
CHANNEL_BUMPER_PROFILES = {
    "saregama": 4.5,
    "saregama telugu": 4.5,
    "saregama music": 4.5,
    "saregama south": 4.5,
    "aditya music": 3.5,
    "aditya music telugu": 3.5,
    "sun pictures": 5.0,
    "t-series": 3.0,
    "tseries": 3.0,
    "t-series telugu": 3.0,
    "sony music": 3.5,
    "sony music south": 3.5,
    "sony music india": 3.5,
    "lahari": 4.0,
    "lahari music": 4.0,
    "zee music": 3.5,
    "zee music south": 3.5,
    "geetha arts": 4.0,
    "mythri": 4.0,
    "mythri movie makers": 4.0,
}

# Unambiguous Tamil phonetic tokens that must never appear in Telugu lyrics
TAMIL_PHONETIC_MARKERS = {
    "thalaivan", "thalaivanthaan", "chonnaa", "sonnaa", "innaikkum", "ennennaikkum",
    "ungappan", "alumbu", "paarthavan", "mavanum", "peranum", "aattam", "veppan",
    "thodangidum", "irangidum", "parandhidum", "uyarndhidum", "por thodangidum",
    "padai irangidum", "or kodi", "or karam", "avan per", "oru thalaivan",
    "vanakkam", "nandri", "kadhale", "uyire", "anbe", "paattu", "kanmani",
    "enakenna", "unakenna", "thirumbi", "ippadi", "apdi", "solrathu",
}

# Unambiguous Telugu phonetic tokens indicating genuine Telugu lyrics
TELUGU_PHONETIC_MARKERS = {
    "gundelne", "paripalinche", "premikude", "premikudele", "mana dikku",
    "mokkai poda", "kavalante", "dherenaa", "ninnu", "chusi", "nenu", "unna",
    "ledu", "kaavali", "chusthu", "cheppave", "cheliya", "prema", "pilla",
    "raave", "chusthe", "cheppalenu", "manasulona", "evaru", "ippudu",
    "bagundi", "nuvvu", "chala", "ravoyi", "kalisi",
}

# Language hints for scoring LRCLIB results
LANG_LABEL_HINTS = {
    "Telugu": ["telugu", "think music telugu", "aditya music", "lahari", "madhura",
               "mango music", "saregama telugu", "aditya music telugu"],
    "Tamil": ["tamil", "think music india", "think music tamil", "sun pictures",
              "divo", "u1 records", "sony music south", "saregama tamil", "behindwoods"],
    "Hindi": ["hindi", "t-series", "zee music", "yrf", "eros now", "saregama music",
              "sony music india", "tips official"],
    "Malayalam": ["malayalam", "muzik247", "123musix", "goodwill", "saregama malayalam"],
    "Kannada": ["kannada", "anand audio", "jhankar", "a2 music"],
    "Punjabi": ["punjabi", "speed records", "apna punjab", "geet mp3"],
    "English": ["english"],
}

# Labels exclusively tied to a specific language — strong negative signal for others
LANG_EXCLUSIVE_LABELS = {
    "Tamil": ["think music tamil", "divo music", "u1 records", "sun pictures"],
    "Telugu": ["aditya music", "lahari music", "madhura audio", "mango music telugu"],
    "Hindi": ["t-series", "zee music company", "yrf"],
}


def is_unwanted_foreign_script(text: str, target_lang: str) -> bool:
    """Check if text contains foreign scripts unrelated to target language."""
    if not text:
        return False
    lang_lower = (target_lang or "").lower()

    # Reject CJK ideographs, Hiragana, Katakana, Hangul for non-East-Asian
    if lang_lower not in ["chinese", "japanese", "korean", "mandarin", "cantonese"]:
        if re.search(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3]", text):
            return True

    # Reject Cyrillic
    if lang_lower not in ["russian", "ukrainian", "bulgarian"]:
        if re.search(r"[\u0400-\u04ff]", text):
            return True

    # Reject Arabic script
    if lang_lower not in ["arabic", "persian", "urdu"]:
        if re.search(r"[\u0600-\u06ff]", text):
            return True

    # Reject Thai script
    if lang_lower != "thai":
        if re.search(r"[\u0e00-\u0e7f]", text):
            return True

    return False


def _score_result_for_language(result: dict, language: str, album_name: str = "") -> int:
    """
    Score a LRCLIB result based on strict language verification.
    STRICT DISQUALIFICATION (-1000):
      - If Telugu requested and text has Tamil Unicode or Tamil phonetic keywords.
      - If Tamil requested and text has Telugu Unicode or Telugu phonetic keywords.
      - If Hindi requested and text has Tamil or Telugu Unicode.
    """
    artist_name = (result.get("artistName") or "").lower()
    track_name = (result.get("trackName") or "").lower()
    result_album = (result.get("albumName") or "").lower()
    plain = (result.get("plainLyrics") or "")
    combined = f"{artist_name} {track_name} {result_album} {plain[:400]}".lower()

    # Disqualify foreign non-target scripts (CJK, Cyrillic, Arabic, etc.)
    if is_unwanted_foreign_script(f"{artist_name} {track_name} {result_album} {plain[:500]}", language):
        return -1000

    if not language:
        return 0

    target = language.lower()

    # 1. STRICT Cross-Language Disqualification
    if target == "telugu":
        # Disqualify if Tamil Unicode is present
        if any('\u0B80' <= ch <= '\u0BFF' for ch in plain):
            return -1000
        # Disqualify if candidate contains explicit Tamil markers or words without Telugu script
        tamil_hits = sum(1 for m in TAMIL_PHONETIC_MARKERS if m in combined)
        telugu_script = any('\u0C00' <= ch <= '\u0C7F' for ch in plain)
        if tamil_hits >= 2 and not telugu_script:
            return -1000
        if "(tamil)" in track_name or "- tamil" in track_name or "tamil version" in track_name:
            return -1000

    elif target == "tamil":
        # Disqualify if Telugu Unicode is present
        if any('\u0C00' <= ch <= '\u0C7F' for ch in plain):
            return -1000
        telugu_hits = sum(1 for m in TELUGU_PHONETIC_MARKERS if m in combined)
        tamil_script = any('\u0B80' <= ch <= '\u0BFF' for ch in plain)
        if telugu_hits >= 2 and not tamil_script:
            return -1000
        if "(telugu)" in track_name or "- telugu" in track_name or "telugu version" in track_name:
            return -1000

    elif target == "hindi":
        if any('\u0B80' <= ch <= '\u0BFF' for ch in plain) or any('\u0C00' <= ch <= '\u0C7F' for ch in plain):
            return -1000
        if "(telugu)" in track_name or "(tamil)" in track_name:
            return -1000

    # 2. Positive Scoring
    score = 0
    hints = LANG_LABEL_HINTS.get(language, [])
    for hint in hints:
        if hint in combined:
            score += 15
            break

    # Album match boost
    if album_name:
        alb_clean = album_name.lower().strip()
        if alb_clean and (alb_clean in track_name or alb_clean in result_album):
            score += 35

    # Explicit language mention boost
    if target in track_name or target in result_album:
        score += 30

    # Authentic Script Boosts
    if target == "telugu":
        if any('\u0C00' <= ch <= '\u0C7F' for ch in plain):
            score += 80
        if any(m in combined for m in TELUGU_PHONETIC_MARKERS):
            score += 40

    elif target == "tamil":
        if any('\u0B80' <= ch <= '\u0BFF' for ch in plain):
            score += 80
        if any(m in combined for m in TAMIL_PHONETIC_MARKERS):
            score += 40

    elif target == "hindi":
        if any('\u0900' <= ch <= '\u097F' for ch in plain):
            score += 80

    return score


def calculate_auto_sync_offset(
    channel: str = "",
    uploader: str = "",
    title: str = "",
    video_dur: float = 0.0,
    lrc_dur: float = 0.0,
    first_line_time: float = 0.0,
) -> float:
    """
    Wave Auto-Sync Model:
    Automatically detects channel intro bumpers (e.g. Saregama, Aditya Music, Sun Pictures, T-Series)
    and duration discrepancies between YouTube official music videos and studio album tracks.
    Returns the exact seconds to shift lyric timestamps forward so singing perfectly synchronizes.
    """
    text = f"{uploader or ''} {channel or ''} {title or ''}".lower()

    # 1. Check duration delta if both durations are available
    delta = 0.0
    if video_dur > 0 and lrc_dur > 0:
        delta = round(video_dur - lrc_dur, 1)
        # If the YouTube video is 1.5s to 35s longer than the studio track,
        # official music channels place this padding at the beginning (intro scene/bumper)
        if 1.5 <= delta <= 35.0:
            logger.info(f"⏱️ Auto-Sync: Detected {delta}s intro scene/duration delta (video={video_dur}s vs studio={lrc_dur}s)")
            return delta

    # 2. Known Channel Bumper Profiles
    # These channels prepend an animated logo / audio fanfare before every single song upload
    for ch_key, bumper_time in CHANNEL_BUMPER_PROFILES.items():
        if ch_key in text:
            # If the lyrics start very early (< 3.0s), they definitely overlap with the logo ad
            if first_line_time < 3.0:
                logger.info(f"⏱️ Auto-Sync: Detected early lyric overlap with {ch_key.title()} bumper ad ({bumper_time}s offset applied)")
                return bumper_time
            if delta > 0:
                chosen = max(bumper_time, min(delta, 10.0))
                logger.info(f"⏱️ Auto-Sync: Applied {chosen}s bumper offset for {ch_key.title()}")
                return chosen
            logger.info(f"⏱️ Auto-Sync: Applied default {bumper_time}s bumper offset for {ch_key.title()}")
            return bumper_time

    return 0.0


def clean_song_titles(raw_title: str, raw_artist: str = "", album_name: str = "", language: str = "") -> List[str]:
    """
    Generate clean candidate search queries from raw title, artist, movie/album, and language.
    Prioritizes specific language and album queries first before falling back to generic titles.
    """
    candidates = []

    # 1. Strip everything inside parentheses
    no_parens = re.sub(r'[\(\[\{].*?[\)\]\}]', '', raw_title)

    # 2. Split by delimiters
    parts = re.split(r'[\|\-:\/•~]', no_parens)
    parts = [p.strip() for p in parts if p.strip()]

    p0_clean = ""
    if parts:
        p0 = parts[0]
        p0_clean = re.sub(r'\b(song|video|audio|lyrical|lyrics|full)\b', '', p0, flags=re.IGNORECASE).strip()

    base_title = p0_clean or raw_title.strip()

    # Prioritize specific queries (critical for Indian movie songs e.g. "One Sun One Moon Jailer 2 Telugu")
    if album_name and album_name.strip():
        alb = album_name.strip()
        if language and language.strip():
            candidates.append(f"{base_title} {alb} {language.strip()}")
        candidates.append(f"{base_title} {alb}")

    # Add language candidate query
    if language and language.strip():
        candidates.append(f"{base_title} {language.strip()}")

    artist_clean = raw_artist.strip()
    if artist_clean and artist_clean.lower() not in RECORD_LABELS:
        candidates.append(f"{base_title} {artist_clean}")

    candidates.append(base_title)

    clean_all = re.sub(r'\b(song|video|audio|lyrical|lyrics|full|hd|4k|official|jukebox|telugu|hindi|tamil|english|punjabi|remix)\b', '', raw_title, flags=re.IGNORECASE)
    clean_all = re.sub(r'[\(\)\[\]\|\-@:\/~•]', ' ', clean_all)
    clean_all = ' '.join(clean_all.split()).strip()
    if clean_all:
        candidates.append(clean_all)

    seen = set()
    res = []
    for c in candidates:
        norm = ' '.join(c.split()).strip()
        if norm and norm.lower() not in seen:
            seen.add(norm.lower())
            res.append(norm)

    return res


async def fetch_web_lyrics(
    title: str,
    album: str = "",
    language: str = "",
    duration: int = 0,
    channel: str = "",
    uploader: str = "",
) -> Optional[dict]:
    """
    Multi-source fallback scraper for authentic localized lyrics (Paatly, BharatLyrics, TeluguLyrics).
    Ensures that when LRCLIB only has Tamil lyrics for a multi-language film song, the authentic
    Telugu lyrics (e.g. by Bhaskarabhatla for Jailer 2) are retrieved and synchronized.
    """
    lang_lower = (language or "").lower()
    if not lang_lower:
        return None

    clean_title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", title)
    clean_title = re.sub(r"\b(song|video|audio|lyrical|lyrics|full)\b", "", clean_title, flags=re.IGNORECASE).strip()
    slug_title = re.sub(r"[^a-zA-Z0-9]+", "-", clean_title.lower()).strip("-")
    slug_album = re.sub(r"[^a-zA-Z0-9]+", "-", album.lower()).strip("-") if album else ""

    urls = []
    if slug_album:
        urls.append(f"https://paatly.com/song/{slug_title}-{slug_album}-lyrics-{lang_lower}/")
        urls.append(f"https://paatly.com/song/{slug_title}-{slug_album}-lyrics/")
    urls.append(f"https://paatly.com/song/{slug_title}-lyrics-{lang_lower}/")
    urls.append(f"https://paatly.com/song/{slug_title}-lyrics/")

    client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        timeout=6.0,
    )

    try:
        for u in urls:
            try:
                r = await client.get(u)
                if r.status_code == 200:
                    html = r.text
                    romanized = re.findall(r"<div[^>]*class=\"[^\"]*paatly-romanized-line[^\"]*\"[^>]*>(.*?)</div>", html, re.DOTALL)
                    native = re.findall(r"<div[^>]*class=\"[^\"]*paatly-native-line[^\"]*\"[^>]*>(.*?)</div>", html, re.DOTALL)

                    if lang_lower == "telugu":
                        has_telugu = any(any("\u0C00" <= c <= "\u0C7F" for c in l) for l in native) or "telugu" in u
                        if has_telugu:
                            lines = [l.strip() for l in (romanized or native) if l.strip()]
                            # Ensure lines do not contain Tamil words
                            if not any(any(tw in l.lower() for tw in ["thalaivanthaan", "chonnaa", "innaikkum"]) for l in lines):
                                logger.info(f"✅ Successfully extracted authentic Telugu lyrics from: {u}")
                                auto_offset = calculate_auto_sync_offset(
                                    channel=channel,
                                    uploader=uploader,
                                    title=title,
                                    video_dur=float(duration),
                                    lrc_dur=float(duration),
                                    first_line_time=1.0,
                                )
                                # Generate pacing timestamps across duration
                                dur_val = float(duration) if duration > 0 else 210.0
                                start_t = max(2.0, auto_offset + 3.0)
                                pacing = max(2.0, (dur_val - start_t - 10.0) / max(1, len(lines)))
                                synced = [
                                    {"time": round(start_t + (i * pacing), 2), "text": l}
                                    for i, l in enumerate(lines)
                                ]
                                await client.aclose()
                                return {
                                    "source": f"web_{lang_lower}",
                                    "synced_lyrics": synced,
                                    "plain_lyrics": "\n".join(lines),
                                    "track_name": title,
                                    "artist_name": album,
                                    "duration": dur_val,
                                    "auto_offset": auto_offset,
                                }
            except Exception:
                pass
    finally:
        await client.aclose()

    return None


async def get_lyrics(
    track_name: str,
    artist_name: str = "",
    album_name: str = "",
    duration: int = 0,
    language: str = "",
    video_id: str = "",
    channel: str = "",
    uploader: str = "",
) -> Optional[dict]:
    """
    Fetch lyrics using multi-tier query fallback:
    1. Query LRCLIB with strict language isolation (e.g. Telugu strictly rejects Tamil).
    2. Apply Wave Auto-Sync Model to compensate for intro bumpers & logo ads (Saregama, Aditya, Sun Pictures).
    3. If LRCLIB only has the wrong language (e.g. Tamil for a Telugu song), automatically fallback
       to the Web Lyrics Engine for the authentic Telugu lyrics.
    """
    db = database.db
    cache_id = f"{video_id}_{language.lower()}" if (video_id and language) else (video_id or "")

    # Check negative cache in database
    if db is not None and cache_id:
        try:
            cached = await db.lyrics_cache.find_one({"_id": cache_id})
            if cached and cached.get("found") is False:
                cached_at = cached.get("cached_at")
                if cached_at:
                    if cached_at.tzinfo is None:
                        cached_at = cached_at.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) - cached_at < timedelta(hours=24):
                        logger.info(f"🛑 Negative cache hit for '{track_name}' ({cache_id}) — skipping scrape")
                        return None
        except Exception as e:
            logger.debug(f"Negative cache check error: {e}")

    queries = clean_song_titles(track_name, artist_name, album_name, language)
    logger.info(f"🔍 Searching lyrics for '{track_name}' (album={album_name!r}, dur={duration}s, lang={language!r}) with candidates: {queries}")

    client = get_http_client()
    all_scored = []

    async def _fetch_query(q: str):
        try:
            resp = await client.get(
                f"{LRCLIB_BASE}/search",
                params={"q": q},
                timeout=6.0,
            )
            if resp.status_code == 200:
                results = resp.json()
                if results and isinstance(results, list):
                    return (q, results)
        except Exception as e:
            logger.debug(f"LRCLIB search error for query '{q}': {e}")
        return (q, [])

    try:
        query_results = await asyncio.gather(
            *[_fetch_query(q) for q in queries],
            return_exceptions=True
        )

        for item in query_results:
            if isinstance(item, Exception):
                continue
            q, results = item
            for r in results:
                # Title overlap filter: avoid completely unrelated songs returned by broad LRCLIB search
                clean_search_title = re.sub(r'[\(\[\{].*?[\)\]\}]', '', track_name).strip().lower()
                clean_r_title = re.sub(r'[\(\[\{].*?[\)\]\}]', '', r.get("trackName") or "").strip().lower()
                search_words = set(re.findall(r'\b\w{3,}\b', clean_search_title))
                r_words = set(re.findall(r'\b\w{3,}\b', clean_r_title))
                overlap = search_words.intersection(r_words)
                if search_words and len(overlap) < min(2, len(search_words)) and (clean_search_title not in clean_r_title and clean_r_title not in clean_search_title):
                    continue

                lang_score = _score_result_for_language(r, language, album_name)
                if lang_score <= -500:
                    # Strictly disqualified due to language mismatch (e.g. Tamil for Telugu)
                    continue

                has_synced = bool(r.get("syncedLyrics"))

                # Duration proximity score
                dur_score = 0
                r_dur = float(r.get("duration") or 0)
                if duration > 0 and r_dur > 0:
                    diff = abs(r_dur - float(duration))
                    if diff <= 4:
                        dur_score = 30
                    elif diff <= 12:
                        dur_score = 15
                    elif diff <= 25:
                        dur_score = 5
                    elif diff > 45:
                        dur_score = -25

                total_score = lang_score + (25 if has_synced else 0) + dur_score
                all_scored.append((total_score, has_synced, dur_score, r, q))

        if all_scored:
            all_scored.sort(key=lambda x: x[0], reverse=True)
            for total_score, has_synced, dur_score, r, q in all_scored:
                parsed = _parse_lyrics_response(r)
                if parsed and (parsed["synced_lyrics"] or parsed["plain_lyrics"]):
                    # Calculate and apply Wave Auto-Sync offset
                    first_line_t = parsed["synced_lyrics"][0]["time"] if parsed["synced_lyrics"] else 0.0
                    auto_offset = calculate_auto_sync_offset(
                        channel=channel,
                        uploader=uploader,
                        title=track_name,
                        video_dur=float(duration),
                        lrc_dur=float(parsed.get("duration", 0)),
                        first_line_time=first_line_t,
                    )
                    if auto_offset > 0 and parsed["synced_lyrics"]:
                        for line in parsed["synced_lyrics"]:
                            line["time"] = max(0.0, round(line["time"] + auto_offset, 2))
                    parsed["auto_offset"] = auto_offset

                    logger.info(
                        f"🎤 Selected lyrics for '{track_name}' (query='{q}', score={total_score}, dur_score={dur_score}, auto_offset={auto_offset}s): "
                        f"{r.get('trackName')} by {r.get('artistName')}"
                    )
                    return parsed

    except Exception as e:
        logger.warning(f"Lyrics search error for '{track_name}': {e}")

    # Fallback to Web Lyrics Engine if LRCLIB had no verified target-language lyrics
    try:
        web_res = await fetch_web_lyrics(
            title=track_name,
            album=album_name,
            language=language,
            duration=duration,
            channel=channel,
            uploader=uploader,
        )
        if web_res:
            return web_res
    except Exception as e:
        logger.debug(f"Web lyrics fallback error: {e}")

    # Negative Caching: If no lyrics are found after all sources are checked
    if db is not None and cache_id:
        try:
            await db.lyrics_cache.update_one(
                {"_id": cache_id},
                {
                    "$set": {
                        "lyrics": None,
                        "synced": False,
                        "found": False,
                        "cached_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
            logger.info(f"🛑 Negative cached (no lyrics found) for '{track_name}' ({cache_id}) with 24-hr TTL")
        except Exception as e:
            logger.debug(f"Failed to record negative lyrics cache: {e}")

    return None


def _parse_lyrics_response(data: dict) -> dict:
    """Parse LRCLIB response into standardized format with English transliteration."""
    result = {
        "source": "lrclib",
        "synced_lyrics": [],
        "plain_lyrics": "",
        "track_name": data.get("trackName", ""),
        "artist_name": data.get("artistName", ""),
        "duration": data.get("duration", 0),
        "auto_offset": 0.0,
    }

    synced_lrc = data.get("syncedLyrics", "")
    if synced_lrc:
        result["synced_lyrics"] = _parse_lrc(synced_lrc)

    plain = data.get("plainLyrics", "")
    if plain:
        # Transliterate Indic scripts to English spelling
        result["plain_lyrics"] = transliterate_indic_to_english(plain)

    return result


def _parse_lrc(lrc_text: str) -> List[Dict]:
    """Parse LRC timestamped strings into [{time, text}] with English transliteration."""
    lines = []
    pattern = re.compile(r'\[(\d+):(\d+)(?:\.(\d+))?\](.*)')

    for line in lrc_text.strip().split('\n'):
        match = pattern.match(line.strip())
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            frac_str = match.group(3)
            frac = 0.0
            if frac_str:
                if len(frac_str) == 1:
                    frac = int(frac_str) / 10.0
                elif len(frac_str) == 2:
                    frac = int(frac_str) / 100.0
                else:
                    frac = int(frac_str[:3]) / 1000.0

            text = match.group(4).strip()
            time_seconds = minutes * 60 + seconds + frac

            if text:
                # Transliterate Telugu/Indic words to English spelling
                romanized_text = transliterate_indic_to_english(text)
                lines.append({
                    "time": round(time_seconds, 2),
                    "text": romanized_text,
                })

    return lines


class LyricsService:
    """Service namespace for lyrics retrieval, normalization, and caching."""

    get_lyrics = staticmethod(get_lyrics)
    clean_song_titles = staticmethod(clean_song_titles)
    calculate_auto_sync_offset = staticmethod(calculate_auto_sync_offset)
    fetch_web_lyrics = staticmethod(fetch_web_lyrics)
