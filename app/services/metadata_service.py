"""
Wave - Metadata Service
Enrich tracks with album art, artist info from MusicBrainz and Last.fm.
Optimized for instant search response with graceful fallbacks.
"""

import httpx
import asyncio
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# MusicBrainz API (free, no key needed, rate limit: 1 req/sec)
MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_HEADERS = {
    "User-Agent": "Wave/1.0.0 (personal music app)",
    "Accept": "application/json",
}

# Cover Art Archive (free, no key)
COVERART_BASE = "https://coverartarchive.org"

# Rate limiting for MusicBrainz (1 request per second)
_last_mb_request = 0


async def _rate_limit_mb():
    """Ensure we don't exceed MusicBrainz rate limit."""
    global _last_mb_request
    import time
    now = time.time()
    elapsed = now - _last_mb_request
    if elapsed < 1.1:
        await asyncio.sleep(1.1 - elapsed)
    _last_mb_request = time.time()


async def search_musicbrainz(
    track_name: str,
    artist_name: str = ""
) -> Optional[dict]:
    """Search MusicBrainz for a track to get accurate metadata."""
    await _rate_limit_mb()

    query_parts = [f'recording:"{track_name}"']
    if artist_name:
        query_parts.append(f'artist:"{artist_name}"')
    query = " AND ".join(query_parts)

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                f"{MUSICBRAINZ_BASE}/recording",
                params={"query": query, "limit": 2, "fmt": "json"},
                headers=MUSICBRAINZ_HEADERS,
            )

            if resp.status_code == 200:
                data = resp.json()
                recordings = data.get("recordings", [])

                if recordings:
                    rec = recordings[0]
                    artists = rec.get("artist-credit", [])
                    artist = artists[0]["name"] if artists else artist_name

                    releases = rec.get("releases", [])
                    album = ""
                    release_id = ""
                    release_date = ""
                    if releases:
                        album = releases[0].get("title", "")
                        release_id = releases[0].get("id", "")
                        release_date = releases[0].get("date", "")

                    return {
                        "musicbrainz_id": rec.get("id", ""),
                        "title": rec.get("title", track_name),
                        "artist": artist,
                        "album": album,
                        "release_id": release_id,
                        "release_date": release_date,
                    }
    except Exception as e:
        logger.debug(f"MusicBrainz search skipped: {e}")

    return None


async def enrich_track(track: dict) -> dict:
    """Enrich a track with album art and metadata."""
    if not track.get("album_art"):
        # Default high-res thumbnail as album art
        track["album_art"] = track.get("thumbnail") or f"https://i.ytimg.com/vi/{track.get('video_id', '')}/hqdefault.jpg"
    return track


async def search_with_metadata(
    query: str,
    max_results: int = 20,
    filter_mode: str = "song",
) -> List[dict]:
    """Search YouTube and ensure every track has clean artwork and metadata."""
    from app.services.youtube_service import search_youtube

    # Get YouTube results immediately with official and duration filtering
    tracks = await search_youtube(query, max_results, filter_mode=filter_mode)

    for track in tracks:
        if not track.get("album_art"):
            track["album_art"] = track.get("thumbnail") or f"https://i.ytimg.com/vi/{track.get('video_id', '')}/hqdefault.jpg"

    return tracks
