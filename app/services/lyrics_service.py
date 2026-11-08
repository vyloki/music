"""
Wave - Lyrics Service
Multi-tier lyrics search using LRCLIB API with smart title/artist normalization
and automatic Indic-to-English (Romanized/English spelling) transliteration.
Free, no API key needed.
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
    "vel records", "times music", "tips telugu", "aditya music telugu",
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

    # If target is not East Asian, reject CJK ideographs, Hiragana, Katakana, Hangul
    if lang_lower not in ["chinese", "japanese", "korean", "mandarin", "cantonese"]:
        if re.search(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3]", text):
            return True

    # If target is not Russian/Cyrillic, reject Cyrillic
    if lang_lower not in ["russian", "ukrainian", "bulgarian"]:
        if re.search(r"[\u0400-\u04ff]", text):
            return True

    # If target is not Arabic/Persian/Urdu, reject Arabic script
    if lang_lower not in ["arabic", "persian", "urdu"]:
        if re.search(r"[\u0600-\u06ff]", text):
            return True

    # If target is not Thai, reject Thai script
    if lang_lower != "thai":
        if re.search(r"[\u0e00-\u0e7f]", text):
            return True

    return False


def _score_result_for_language(result: dict, language: str, album_name: str = "") -> int:
    """
    Score a LRCLIB result based on how well it matches the target language.
    Strictly disqualifies foreign scripts (e.g. Chinese CJK when Telugu/Tamil/Hindi/English requested).
    """
    artist_name = (result.get("artistName") or "").lower()
    track_name = (result.get("trackName") or "").lower()
    result_album = (result.get("albumName") or "").lower()
    plain = (result.get("plainLyrics") or "")
    combined = f"{artist_name} {track_name} {result_album} {plain[:300]}".lower()

    # Strictly reject foreign script matches (e.g. Chinese pop song matching English word)
    if is_unwanted_foreign_script(f"{artist_name} {track_name} {result_album} {plain[:500]}", language):
        return -1000

    if not language:
        return 0

    score = 0
    hints = LANG_LABEL_HINTS.get(language, [])

    for hint in hints:
        if hint in combined:
            score += 15
            break

    # If movie/album is provided, give strong boost if candidate mentions it
    if album_name:
        alb_clean = album_name.lower().strip()
        if alb_clean and (alb_clean in track_name or alb_clean in result_album):
            score += 35

    # If target language name explicitly appears in track title or album name
    if language.lower() in track_name or language.lower() in result_album:
        score += 25

    # If looking for Telugu, check if plain lyrics contain Telugu Unicode
    if language.lower() == "telugu":
        if any('\u0C00' <= ch <= '\u0C7F' for ch in plain):
            score += 35
        # Penalize Tamil unicode if Telugu requested
        if any('\u0B80' <= ch <= '\u0BFF' for ch in plain):
            score -= 30

    # If looking for Tamil, check if plain lyrics contain Tamil Unicode
    elif language.lower() == "tamil":
        if any('\u0B80' <= ch <= '\u0BFF' for ch in plain):
            score += 35
        if any('\u0C00' <= ch <= '\u0C7F' for ch in plain):
            score -= 30

    # If looking for Hindi, check if plain lyrics contain Devanagari Unicode
    elif language.lower() == "hindi":
        if any('\u0900' <= ch <= '\u097F' for ch in plain):
            score += 35

    # Penalize exclusive hints from other languages
    for lang, hint_list in LANG_LABEL_HINTS.items():
        if lang.lower() == language.lower():
            continue
        for hint in hint_list:
            if hint in combined:
                score -= 10
                break

    for lang, labels in LANG_EXCLUSIVE_LABELS.items():
        if lang.lower() == language.lower():
            continue
        for label in labels:
            if label in combined:
                score -= 25
                break

    return score


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

    # Prioritize specific queries (critical for Indian movie songs e.g. "Boom Boom Dude Telugu")
    if album_name and album_name.strip():
        alb = album_name.strip()
        if language and language.strip():
            candidates.append(f"{base_title} {alb} {language.strip()}")
        candidates.append(f"{base_title} {alb}")

    # Add language candidate query (e.g. "Boom Boom Telugu")
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


async def get_lyrics(
    track_name: str,
    artist_name: str = "",
    album_name: str = "",
    duration: int = 0,
    language: str = "",
    video_id: str = "",
) -> Optional[dict]:
    """
    Fetch lyrics from LRCLIB using smart multi-tier query fallback.
    Language-aware, script-filtering, duration-aware, and album-aware.
    Automatically transliterates Telugu/Indic lyrics to English spelling.
    Negative-caches queries that yield no lyrics to avoid repeated scraping for instrumentals.
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
                lang_score = _score_result_for_language(r, language, album_name)
                if lang_score <= -500:
                    # Foreign script disqualified
                    continue

                has_synced = bool(r.get("syncedLyrics"))

                # Calculate duration proximity score
                dur_score = 0
                r_dur = float(r.get("duration") or 0)
                if duration > 0 and r_dur > 0:
                    diff = abs(r_dur - float(duration))
                    if diff <= 4:
                        dur_score = 30  # Exact or near-exact song length match
                    elif diff <= 12:
                        dur_score = 15
                    elif diff <= 25:
                        dur_score = 5
                    elif diff > 45:
                        dur_score = -25  # Mismatched edit/remix

                total_score = lang_score + (25 if has_synced else 0) + dur_score
                all_scored.append((total_score, has_synced, dur_score, r, q))

        if all_scored:
            all_scored.sort(key=lambda x: x[0], reverse=True)
            for total_score, has_synced, dur_score, r, q in all_scored:
                parsed = _parse_lyrics_response(r)
                if parsed and (parsed["synced_lyrics"] or parsed["plain_lyrics"]):
                    logger.info(
                        f"🎤 Selected lyrics for '{track_name}' (query='{q}', score={total_score}, dur_score={dur_score}): "
                        f"{r.get('trackName')} by {r.get('artistName')}"
                    )
                    return parsed

    except Exception as e:
        logger.warning(f"Lyrics search error for '{track_name}': {e}")

    # Negative Caching: If no lyrics are found after all sources are checked, cache in db.lyrics_cache with 24-hr TTL
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

