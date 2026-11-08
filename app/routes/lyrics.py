"""
Wave - Lyrics Routes
Fetch and serve song lyrics with sync timestamps.
"""

from fastapi import APIRouter, Depends, Query
from app.services.lyrics_service import get_lyrics
from app.utils.security import get_optional_user
from app.database import get_db
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lyrics", tags=["Lyrics"])


@router.get(
    "/{video_id}",
    summary="Get lyrics for a track"
)
async def fetch_lyrics(
    video_id: str,
    title: str = Query("", description="Track title"),
    artist: str = Query("", description="Artist name"),
    movie: str = Query("", description="Movie / Album name"),
    duration: int = Query(0, description="Track duration in seconds"),
    language: str = Query("", description="Track language (Telugu, Tamil, Hindi, etc.)"),
    user=Depends(get_optional_user),
    db=Depends(get_db),
):
    """Fetch synced or plain lyrics for a track. Language-aware and movie-aware caching."""
    # Language-keyed cache so Telugu and Tamil lyrics for the same video_id are stored separately
    cache_id = f"{video_id}_{language.lower()}" if language else video_id

    # Check cache
    if db is not None:
        try:
            cached = await db.lyrics_cache.find_one({"_id": cache_id})
            if cached:
                if cached.get("found") is False:
                    # Negative cache hit within 24 hours
                    cached_at = cached.get("cached_at")
                    if cached_at:
                        if cached_at.tzinfo is None:
                            cached_at = cached_at.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) - cached_at < timedelta(hours=24):
                            logger.info(f"📦 Lyrics negative cache hit: {cache_id}")
                            return {
                                "video_id": video_id,
                                "synced": [],
                                "plain": "",
                                "has_synced": False,
                                "source": "none",
                            }
                elif cached.get("synced_lyrics") or cached.get("plain_lyrics"):
                    logger.info(f"📦 Lyrics cache hit: {cache_id}")
                    return {
                        "video_id": video_id,
                        "synced": cached.get("synced_lyrics", []),
                        "plain": cached.get("plain_lyrics", ""),
                        "has_synced": len(cached.get("synced_lyrics", [])) > 0,
                        "source": cached.get("source", "cache"),
                    }
        except Exception:
            pass

    # Get track info from song_cache if title not provided
    if not title and db is not None:
        try:
            track_cache = await db.song_cache.find_one({"_id": video_id})
            if track_cache:
                title = track_cache.get("track_name") or track_cache.get("title", "")
                artist = track_cache.get("artist", "")
                movie = track_cache.get("movie") or movie
                duration = track_cache.get("duration", 0)
                if not language:
                    language = track_cache.get("language", "")
        except Exception:
            pass

    if not title:
        title = f"track {video_id}"

    # Fetch from LRCLIB (now language, movie, and duration-aware)
    result = await get_lyrics(
        track_name=title,
        artist_name=artist,
        album_name=movie,
        duration=duration,
        language=language,
        video_id=video_id,
    )

    if result:
        if db is not None:
            try:
                await db.lyrics_cache.update_one(
                    {"_id": cache_id},
                    {
                        "$set": {
                            **result,
                            "found": True,
                            "cached_at": datetime.now(timezone.utc),
                        }
                    },
                    upsert=True,
                )
            except Exception:
                pass

        return {
            "video_id": video_id,
            "synced": result.get("synced_lyrics", []),
            "plain": result.get("plain_lyrics", ""),
            "has_synced": len(result.get("synced_lyrics", [])) > 0,
            "source": result.get("source", "lrclib"),
        }

    # Negative Caching: record that no lyrics were found so instrumentals don't re-trigger scraping
    if db is not None:
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
                upsert=True,
            )
        except Exception:
            pass

    return {
        "video_id": video_id,
        "synced": [],
        "plain": "",
        "has_synced": False,
        "source": "none",
    }
