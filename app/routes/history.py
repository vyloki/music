"""
Wave - Listening History Routes
Track what the user listens to with MongoDB storage and optional authentication.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from app.database import get_db
from app.utils.security import get_optional_user
from app.models.playlist import HistoryEntry
from bson import ObjectId
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/history", tags=["History"])


async def _record_history(db, user_id: ObjectId, data: HistoryEntry) -> None:
    """Offload document insertion and daily tracking updates to background task."""
    try:
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "video_id": data.video_id,
            "title": data.title,
            "artist": data.artist,
            "thumbnail": data.thumbnail,
            "duration": getattr(data, "duration", 0) or 0,
            "movie": data.movie or "",
            "language": data.language or "",
            "subtitle": data.subtitle or "",
            "played_at": now,
        }
        await db.listening_history.insert_one(doc)

        # Update daily tracking
        today_str = now.strftime("%Y-%m-%d")
        try:
            await db.daily_tracking.update_one(
                {"user_id": user_id, "date": today_str},
                {
                    "$inc": {"play_count": 1},
                    "$set": {"last_played": now},
                    "$setOnInsert": {"user_id": user_id, "date": today_str},
                },
                upsert=True,
            )
        except Exception as te:
            logger.debug(f"Daily tracking update note: {te}")
    except Exception as e:
        logger.debug(f"History background record error: {e}")


@router.post("", summary="Record a play event")
async def record_play(
    data: HistoryEntry,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_optional_user),
    db=Depends(get_db),
):
    """Record that a track was played. Works for both authenticated users and guests."""
    if user and db is not None:
        user_id = ObjectId(user["_id"]) if ObjectId.is_valid(user["_id"]) else user["_id"]
        background_tasks.add_task(_record_history, db, user_id, data)

    return {"status": "recorded"}


@router.get("", summary="Get recent listening history")
async def get_history(
    limit: int = Query(default=30, ge=1, le=100),
    user: dict = Depends(get_optional_user),
    db=Depends(get_db),
):
    """Get the user's recent listening history."""
    if not user or db is None:
        return {"history": []}

    try:
        user_id = ObjectId(user["_id"]) if ObjectId.is_valid(user["_id"]) else user["_id"]
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$sort": {"played_at": -1}},
            {
                "$group": {
                    "_id": "$video_id",
                    "played_at": {"$first": "$played_at"},
                    "title": {"$first": "$title"},
                    "artist": {"$first": "$artist"},
                    "thumbnail": {"$first": "$thumbnail"},
                    "duration": {"$first": "$duration"},
                    "movie": {"$first": "$movie"},
                    "language": {"$first": "$language"},
                    "subtitle": {"$first": "$subtitle"},
                }
            },
            {"$sort": {"played_at": -1}},
            {"$limit": limit},
        ]

        cursor = db.listening_history.aggregate(pipeline)
        history = []
        async for doc in cursor:
            history.append({
                "video_id": doc["_id"],
                "title": doc.get("title", ""),
                "artist": doc.get("artist", ""),
                "thumbnail": doc.get("thumbnail", ""),
                "duration": doc.get("duration", 0) or 0,
                "movie": doc.get("movie", ""),
                "language": doc.get("language", ""),
                "subtitle": doc.get("subtitle", ""),
                "played_at": doc.get("played_at"),
            })

        return {"history": history}
    except Exception as e:
        logger.warning(f"History fetch error: {e}")
        return {"history": []}


@router.get("/top", summary="Get most played tracks")
async def get_top(
    limit: int = Query(default=20, ge=1, le=50),
    user: dict = Depends(get_optional_user),
    db=Depends(get_db),
):
    """Get the user's most frequently played tracks."""
    if not user or db is None:
        return {"tracks": []}

    try:
        user_id = ObjectId(user["_id"]) if ObjectId.is_valid(user["_id"]) else user["_id"]
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$sort": {"played_at": -1}},
            {
                "$group": {
                    "_id": "$video_id",
                    "title": {"$first": "$title"},
                    "artist": {"$first": "$artist"},
                    "thumbnail": {"$first": "$thumbnail"},
                    "duration": {"$first": "$duration"},
                    "movie": {"$first": "$movie"},
                    "language": {"$first": "$language"},
                    "subtitle": {"$first": "$subtitle"},
                    "play_count": {"$sum": 1},
                    "last_played": {"$max": "$played_at"},
                }
            },
            {"$sort": {"play_count": -1, "last_played": -1}},
            {"$limit": limit},
        ]
        cursor = db.listening_history.aggregate(pipeline)
        tracks = []
        async for doc in cursor:
            tracks.append({
                "video_id": doc["_id"],
                "title": doc.get("title", ""),
                "artist": doc.get("artist", ""),
                "thumbnail": doc.get("thumbnail", ""),
                "duration": doc.get("duration", 0) or 0,
                "movie": doc.get("movie", ""),
                "language": doc.get("language", ""),
                "subtitle": doc.get("subtitle", ""),
                "play_count": doc.get("play_count", 0),
                "last_played": doc.get("last_played"),
            })
        return {"tracks": tracks}
    except Exception as e:
        logger.warning(f"Top tracks error: {e}")
        return {"tracks": []}


@router.delete("", summary="Clear listening history")
async def clear_history(
    user: dict = Depends(get_optional_user),
    db=Depends(get_db),
):
    """Clear the user's entire listening history."""
    if user and db is not None:
        try:
            user_id = ObjectId(user["_id"]) if ObjectId.is_valid(user["_id"]) else user["_id"]
            await db.listening_history.delete_many({"user_id": user_id})
            await db.daily_tracking.delete_many({"user_id": user_id})
        except Exception:
            pass
    return {"message": "History cleared"}
