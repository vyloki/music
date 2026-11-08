"""
Wave - Stream Service
Audio stream URL management with caching, URL expiry parsing, and recovery.
"""

from app.services.youtube_service import get_stream_url
from app.database import database
from datetime import datetime, timezone, timedelta
import urllib.parse
import logging

logger = logging.getLogger(__name__)

DEFAULT_STREAM_TTL = timedelta(hours=4)


def _extract_url_expiry(url: str) -> datetime:
    """Parse actual expiration timestamp from YouTube videoplayback URL query."""
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        if "expire" in params and params["expire"][0].isdigit():
            expire_ts = int(params["expire"][0])
            # Return 5 minutes before actual expire time for safety margin
            return datetime.fromtimestamp(expire_ts - 300, tz=timezone.utc)
    except Exception:
        pass
    return datetime.now(timezone.utc) + DEFAULT_STREAM_TTL


async def update_stream_cache(video_id: str, stream_info: dict) -> None:
    """Helper to update stream cache in database."""
    db = database.db
    if db is None or not stream_info or not stream_info.get("url"):
        return

    url = stream_info["url"]
    expires_at = _extract_url_expiry(url)

    content_length = stream_info.get("content_length") or stream_info.get("filesize")
    set_data = {
        "stream_url": url,
        "format": stream_info.get("format", ""),
        "ext": stream_info.get("ext", "mp4"),
        "duration": stream_info.get("duration", 0),
        "cached_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    }
    if content_length:
        set_data["content_length"] = int(content_length)
        set_data["filesize"] = int(content_length)

    await db.stream_cache.update_one(
        {"_id": video_id},
        {"$set": set_data},
        upsert=True,
    )
    logger.debug(f"🎵 Stream URL cached for {video_id} (expires: {expires_at})")


async def get_cached_stream_url(video_id: str, force_refresh: bool = False) -> str | None:
    """
    Get a stream URL, using cache if available and not expired.
    If force_refresh is True, bypasses cache and updates with a freshly extracted URL.
    """
    db = database.db

    if not force_refresh and db is not None:
        cached = await db.stream_cache.find_one({
            "_id": video_id,
            "expires_at": {"$gt": datetime.now(timezone.utc)}
        })
        if cached and cached.get("stream_url"):
            logger.debug(f"📦 Stream cache hit: {video_id}")
            return cached["stream_url"]

    # Extract fresh URL from YouTube
    result = await get_stream_url(video_id)
    if not result or not result.get("url"):
        logger.error(f"❌ Failed to extract stream URL for {video_id}")
        return None

    if db is not None:
        await update_stream_cache(video_id, result)

    return result["url"]
