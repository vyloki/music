"""
Wave - Background Tasks
In-process background task tracking with GC protection and graceful shutdown.
"""

import asyncio
import logging
from typing import Callable, Set
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Strong reference set to prevent garbage collection of running tasks
_active_background_tasks: Set[asyncio.Task] = set()


async def run_background(coro_fn: Callable, *args, **kwargs) -> None:
    """
    Fire-and-forget: schedule an async coroutine with GC protection.
    Does not block the caller.
    """
    async def _wrapper():
        try:
            await coro_fn(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Background task error [{coro_fn.__name__}]: {e}")

    task = asyncio.create_task(_wrapper())
    _active_background_tasks.add(task)
    task.add_done_callback(_active_background_tasks.discard)


async def shutdown_background_tasks(timeout: float = 3.0) -> None:
    """Drain background tasks during server shutdown."""
    if not _active_background_tasks:
        return
    logger.info(f"⏳ Waiting for {len(_active_background_tasks)} background task(s) to finish...")
    done, pending = await asyncio.wait(_active_background_tasks, timeout=timeout)
    for t in pending:
        t.cancel()


async def prefetch_lyrics(video_id: str, title: str, artist: str, language: str, db) -> None:
    """Pre-warm lyrics cache for a track after it starts playing."""
    from app.services.lyrics_service import get_lyrics

    if db is None:
        return

    cache_id = f"{video_id}_{language.lower()}" if language else video_id
    existing = await db.lyrics_cache.find_one({"_id": cache_id})
    if existing:
        return  # Already cached

    result = await get_lyrics(track_name=title, artist_name=artist, language=language)
    if result:
        try:
            await db.lyrics_cache.update_one(
                {"_id": cache_id},
                {"$set": {**result, "cached_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            logger.debug(f"🎤 Pre-warmed lyrics cache for {video_id} ({language})")
        except Exception as e:
            logger.debug(f"Lyrics prefetch cache write failed: {e}")


async def warm_artist_cache(artist_name: str, language: str, db) -> None:
    """Pre-warm song cache for an artist's top tracks in a given language."""
    from app.services.youtube_service import search_youtube

    query = f"{artist_name} {language} hit songs official audio".strip()
    try:
        tracks = await search_youtube(query, max_results=10, filter_mode="song")
        if db is not None and tracks:
            for t in tracks:
                vid = t.get("video_id")
                if vid:
                    await db.song_cache.update_one(
                        {"_id": vid},
                        {"$set": {**t, "cached_at": datetime.now(timezone.utc)}},
                        upsert=True,
                    )
        logger.debug(f"🎸 Pre-warmed and cached {len(tracks)} tracks for artist '{artist_name}' ({language})")
    except Exception as e:
        logger.debug(f"Artist cache warm failed for {artist_name}: {e}")
