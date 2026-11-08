"""
Wave - Songs Routes
Per-song utilities: language version discovery.
"""

from fastapi import APIRouter, Query
from app.services.youtube_service import get_language_versions, get_video_info
from app.database import get_db
from fastapi import Depends
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/songs", tags=["Songs"])


@router.get("/{video_id}/languages", summary="Get available language versions of a song")
async def get_song_languages(
    video_id: str,
    track_name: str = Query("", description="Song title"),
    movie: str = Query("", description="Movie / album name"),
    db=Depends(get_db),
):
    """
    Discover language versions of a song (Telugu, Tamil, Hindi, Malayalam, Kannada).
    Returns the best matching YouTube video for each language.
    Results are cached in MongoDB to avoid repeated YouTube searches.
    """
    cache_key = f"langver_{video_id}"

    # Check cache (1 hour expiry)
    if db is not None:
        try:
            from datetime import datetime, timezone, timedelta
            cached = await db.song_cache.find_one({
                "_id": cache_key,
                "cached_at": {"$gt": datetime.now(timezone.utc) - timedelta(hours=1)}
            })
            if cached and cached.get("versions"):
                logger.debug(f"📦 Language versions cache hit: {video_id}")
                return {"video_id": video_id, "versions": cached["versions"]}
        except Exception:
            pass

    # If track_name not supplied, try to look it up from song_cache
    if not track_name and db is not None:
        try:
            track_doc = await db.song_cache.find_one({"_id": video_id})
            if track_doc:
                track_name = track_doc.get("track_name") or track_doc.get("title", "")
                movie = movie or track_doc.get("movie", "")
        except Exception:
            pass

    if not track_name:
        # Last resort: fetch from YouTube
        try:
            info = await get_video_info(video_id)
            if info:
                track_name = info.get("track_name") or info.get("title", "")
                movie = movie or info.get("movie", "")
        except Exception:
            pass

    if not track_name:
        return {"video_id": video_id, "versions": []}

    versions = await get_language_versions(
        track_name=track_name,
        movie=movie,
        current_video_id=video_id,
    )

    # Cache result for 1 hour (next request will hit cache)
    if db is not None and versions:
        try:
            from datetime import datetime, timezone
            await db.song_cache.update_one(
                {"_id": cache_key},
                {"$set": {"versions": versions, "cached_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception:
            pass

    return {"video_id": video_id, "versions": versions}
