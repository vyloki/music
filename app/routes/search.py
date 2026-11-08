"""
Wave - Search Routes
Music search endpoints with YouTube + MusicBrainz enrichment, L1 cache, and DB caching.
"""

from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, Query, HTTPException
from app.utils.security import get_optional_user
from app.utils.cache import search_l1_cache
from app.services.youtube_service import (
    search_youtube,
    get_video_info,
    get_youtube_suggestions,
)
from app.services.metadata_service import search_with_metadata, enrich_track
from app.database import get_db
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["Search"])

# Predefined static mood categories
MOOD_CATEGORIES = [
    {"id": "chill", "name": "Chill & Lo-Fi", "query": "chill lofi hip hop beats to relax", "icon": "coffee"},
    {"id": "workout", "name": "Workout & Gym", "query": "workout gym motivation energetic songs", "icon": "zap"},
    {"id": "party", "name": "Party & Dance", "query": "party dance club hit songs", "icon": "flame"},
    {"id": "focus", "name": "Focus & Study", "query": "deep focus instrumental study beats", "icon": "book-open"},
    {"id": "romantic", "name": "Romantic Melodies", "query": "romantic love songs acoustic melody", "icon": "heart"},
    {"id": "sleep", "name": "Deep Sleep", "query": "calm soothing sleep ambient music", "icon": "moon"},
    {"id": "feelgood", "name": "Feel Good", "query": "feel good happy upbeat pop songs", "icon": "sun"},
    {"id": "sad", "name": "Soulful & Melancholy", "query": "sad emotional acoustic heartbreak songs", "icon": "cloud-rain"},
]


@router.get("", summary="Search for songs")
async def search(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    limit: int = Query(default=20, ge=1, le=50, description="Max results"),
    type: str = Query(default="song", description="Search type (song, album, artist, all)"),
    language: str = Query(default="", description="Language filter"),
    enrich: bool = Query(default=True, description="Enrich metadata"),
    user: dict = Depends(get_optional_user),
    db=Depends(get_db),
):
    """
    Search for songs by query.
    Uses L1 in-memory TTL caching and MongoDB persistent caching, with bulk writes for song cache.
    """
    cache_key = f"search:{q}:{type}:{language}"

    # 1. Check in-memory L1 cache (instant O(1))
    cached_l1 = search_l1_cache.get(f"search:{q}:{type}:{language}")
    if cached_l1 is not None:
        if isinstance(cached_l1, dict):
            return cached_l1
        return {
            "query": q,
            "results": cached_l1,
            "total": len(cached_l1),
            "cached": True,
        }

    # 2. Check MongoDB persistent cache
    if db is not None:
        try:
            cached = await db.search_cache.find_one({
                "_id": cache_key,
                "cached_at": {"$gt": datetime.now(timezone.utc).replace(hour=0, minute=0)}
            })
            if not cached:
                cached = await db.search_cache.find_one({
                    "_id": f"search:{q.lower().strip()}:{limit}",
                    "cached_at": {"$gt": datetime.now(timezone.utc).replace(hour=0, minute=0)}
                })
            if cached and cached.get("results"):
                search_l1_cache.set(cache_key, cached["results"], ttl=300.0)
                return {
                    "query": q,
                    "results": cached["results"],
                    "total": len(cached["results"]),
                    "cached": True,
                }
        except Exception as e:
            logger.debug(f"Search cache lookup skipped: {e}")

    # 3. Perform search
    search_q = f"{q} {language}".strip() if language and language.lower() not in q.lower() else q
    if enrich:
        results = await search_with_metadata(search_q, limit)
    else:
        results = await search_youtube(search_q, limit)

    tracks = results
    for t in tracks:
        vid = t.get("video_id") or t.get("id")
        if vid:
            t["id"] = vid
            t["video_id"] = vid

    # 4. Cache results if DB is available (using single bulk write for song cache)
    if db is not None and tracks:
        try:
            await db.search_cache.update_one(
                {"_id": cache_key},
                {
                    "$set": {
                        "results": tracks,
                        "cached_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )

            from pymongo import UpdateOne
            now_utc = datetime.now(timezone.utc)
            ops = [
                UpdateOne(
                    {"video_id": t["id"]},
                    {
                        "$set": {**t, "cached_at": now_utc},
                        "$setOnInsert": {"_id": t["id"]},
                    },
                    upsert=True,
                )
                for t in tracks
                if t.get("id")
            ]
            if ops:
                await db.song_cache.bulk_write(ops, ordered=False)
        except Exception as e:
            logger.debug(f"Search cache save skipped: {e}")

    # Store results in L1 cache
    search_l1_cache.set(cache_key, results, ttl=300.0)

    return {
        "query": q,
        "results": results,
        "total": len(results),
        "cached": False,
    }


@router.get("/trending", summary="Get trending search tracks")
async def trending(
    category: str = Query(default="trending", description="Category ID"),
    limit: int = Query(default=20, ge=1, le=50, description="Max results"),
    language: str = Query(default="", description="Language filter"),
    db=Depends(get_db),
):
    """
    Get trending tracks with L1 caching (TTL: 600s).
    Static categories don't repeatedly query YouTube or database.
    """
    cache_key = f"search:trending:{category}:{limit}:{language}"
    cached = search_l1_cache.get(cache_key)
    if cached is not None:
        return cached

    from app.services.recommendation_service import get_trending_tracks
    target_category = f"{category}_{language}" if language and language.lower() not in category.lower() else category
    tracks = await get_trending_tracks(target_category, limit)
    if not tracks and category != "trending":
        tracks = await get_trending_tracks("trending", limit)

    for t in tracks:
        vid = t.get("video_id") or t.get("id")
        if vid:
            t["id"] = vid
            t["video_id"] = vid

    result = {
        "category": category,
        "tracks": tracks,
        "total": len(tracks),
    }
    search_l1_cache.set(cache_key, result, ttl=600.0)
    return result


@router.get("/moods", summary="Get mood categories and tracks")
async def moods(
    mood: Optional[str] = Query(default=None, description="Mood identifier"),
    limit: int = Query(default=20, ge=1, le=50, description="Max results"),
    db=Depends(get_db),
):
    """
    Get mood categories or mood tracks with L1 caching (TTL: 3600s).
    Static categories don't repeatedly query YouTube or database.
    """
    cache_key = f"search:moods:{mood or 'all'}:{limit}"
    cached = search_l1_cache.get(cache_key)
    if cached is not None:
        return cached

    if not mood:
        result = {
            "moods": MOOD_CATEGORIES,
            "total": len(MOOD_CATEGORIES),
        }
        search_l1_cache.set(cache_key, result, ttl=3600.0)
        return result

    target = next((m for m in MOOD_CATEGORIES if m["id"] == mood.lower()), None)
    query = target["query"] if target else f"{mood} songs"

    tracks = await search_youtube(query, max_results=limit)
    for t in tracks:
        vid = t.get("video_id") or t.get("id")
        if vid:
            t["id"] = vid
            t["video_id"] = vid

    # Bulk cache tracks to database if available
    if db is not None and tracks:
        try:
            from pymongo import UpdateOne
            now_utc = datetime.now(timezone.utc)
            ops = [
                UpdateOne(
                    {"video_id": t["id"]},
                    {
                        "$set": {**t, "cached_at": now_utc},
                        "$setOnInsert": {"_id": t["id"]},
                    },
                    upsert=True,
                )
                for t in tracks
                if t.get("id")
            ]
            if ops:
                await db.song_cache.bulk_write(ops, ordered=False)
        except Exception as e:
            logger.debug(f"Moods song cache bulk write skipped: {e}")

    result = {
        "mood": mood,
        "name": target["name"] if target else mood.capitalize(),
        "tracks": tracks,
        "total": len(tracks),
    }
    search_l1_cache.set(cache_key, result, ttl=3600.0)
    return result


@router.get("/suggestions", summary="Get autocomplete suggestions")
async def suggestions(
    q: str = Query(..., min_length=1, max_length=100, description="Query"),
):
    """Get clean music-focused autocomplete suggestions."""
    from app.services.youtube_service import get_youtube_suggestions
    results = await get_youtube_suggestions(q)
    return {"query": q, "suggestions": results}


@router.get("/track/{video_id}", summary="Get track details")
async def get_track(
    video_id: str,
    user: dict = Depends(get_optional_user),
    db=Depends(get_db),
):
    """Get detailed information for a track."""
    if db is not None:
        try:
            cached = await db.song_cache.find_one({"_id": video_id})
            if cached:
                if user:
                    cached["is_liked"] = video_id in user.get("liked_tracks", [])
                cached.pop("_id", None)
                cached["video_id"] = video_id
                return cached
        except Exception as e:
            logger.debug(f"Track cache lookup skipped: {e}")

    track = await get_video_info(video_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    track = await enrich_track(track)

    if db is not None:
        try:
            await db.song_cache.update_one(
                {"_id": video_id},
                {
                    "$set": {
                        **track,
                        "cached_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
        except Exception:
            pass

    if user:
        track["is_liked"] = video_id in user.get("liked_tracks", [])

    return track
