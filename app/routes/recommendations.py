"""
Wave - Recommendations & Trending Routes
"""

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from app.services.recommendation_service import (
    get_trending_tracks,
    get_personalized_home_feed,
    get_home_feed,
    get_song_radio,
    get_next_recommendation,
    record_co_listen,
    get_time_of_day_context,
    CATEGORIES,
)
from app.utils.security import get_optional_user
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


@router.get("/categories", summary="Get music categories")
async def list_categories():
    """Get browse categories."""
    return {"categories": CATEGORIES}


@router.get("/trending", summary="Get trending tracks")
async def trending(
    category: str = Query("trending", description="Category ID"),
    limit: int = Query(15, ge=1, le=30),
    user=Depends(get_optional_user),
):
    """Get trending tracks for a category."""
    tracks = await get_trending_tracks(category, limit)
    return {"category": category, "tracks": tracks, "total": len(tracks)}


@router.get("/feed", summary="Get dynamic personalized home feed")
async def feed(user=Depends(get_optional_user)):
    """Get multi-section home feed with time-of-day intelligence."""
    user_id = str(user["_id"]) if user and "_id" in user else None
    return await get_home_feed(user_id)


@router.get("/contextual", summary="Get current time-of-day and mood context")
async def contextual(user=Depends(get_optional_user)):
    """Get time-of-day greeting, mood profile, and contextual tracks."""
    user_id = str(user["_id"]) if user and "_id" in user else None
    return await get_home_feed(user_id)


@router.get("/radio", summary="Get endless smart song radio recommendations")
async def radio(
    video_id: str = Query(..., description="Currently playing video ID"),
    title: str = Query("", description="Track title"),
    artist: str = Query("", description="Artist name"),
    movie: str = Query("", description="Movie name"),
    language: str = Query("Telugu", description="Language of current song"),
    limit: int = Query(12, ge=1, le=30, description="Number of candidate tracks"),
    user=Depends(get_optional_user),
):
    """
    Get a continuous, scored stream of similar songs for infinite auto-play.
    Combines YouTube similarity, artist hits, transition graph, and language constraints.
    """
    user_id = str(user["_id"]) if user and "_id" in user else None
    current_track = {
        "video_id": video_id,
        "track_name": title,
        "title": title,
        "artist": artist,
        "movie": movie,
        "language": language or "Telugu",
    }
    tracks = await get_song_radio(current_track, user_id=user_id, limit=limit)
    return {
        "video_id": video_id,
        "language": language,
        "tracks": tracks,
        "total": len(tracks),
    }


@router.get("/next", summary="Get next recommended song")
async def next_song(
    current_id: str = Query(..., description="Currently playing video ID"),
    user=Depends(get_optional_user),
):
    """Get the next recommended song based on the current track."""
    track = await get_next_recommendation(current_id)
    return {"track": track}


@router.post("/transition", summary="Record track transition")
async def transition(
    background_tasks: BackgroundTasks,
    from_id: str = Query(..., description="Previous track video ID"),
    to_id: str = Query(..., description="Next track video ID"),
    user=Depends(get_optional_user),
):
    """Record that a user transitioned from track A to track B to build the graph."""
    background_tasks.add_task(record_co_listen, from_id, to_id)
    return {"status": "recorded"}
