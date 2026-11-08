"""
Wave - Playlist Routes
Create, read, update, and delete user playlists and playlist tracks.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_db
from app.models.playlist import (
    PlaylistCreate,
    PlaylistUpdate,
    AddTrackRequest,
)
from app.utils.security import get_current_user
from app.utils.db import to_object_id
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playlists", tags=["Playlists"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a playlist")
async def create_playlist(
    data: PlaylistCreate,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    user_oid = to_object_id(user["_id"], "User")
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user_oid,
        "name": data.name,
        "description": data.description or "",
        "tracks": [],
        "track_count": 0,
        "cover_url": "",
        "created_at": now,
        "updated_at": now,
    }
    result = await db.playlists.insert_one(doc)
    logger.info(f"✅ Playlist created: {data.name}")
    return {
        "id": str(result.inserted_id),
        "name": data.name,
        "description": data.description or "",
        "track_count": 0,
        "created_at": now,
    }


@router.get("", summary="List user playlists")
async def list_playlists(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    user_oid = to_object_id(user["_id"], "User")
    pipeline = [
        {"$match": {"user_id": user_oid}},
        {"$sort": {"created_at": -1}},
        {"$limit": 100},
        {
            "$project": {
                "name": 1,
                "description": 1,
                "cover_url": 1,
                "is_public": 1,
                "created_at": 1,
                "updated_at": 1,
                "track_count": {
                    "$ifNull": [
                        "$track_count",
                        {"$size": {"$ifNull": ["$tracks", []]}},
                    ]
                },
            }
        },
    ]
    cursor = db.playlists.aggregate(pipeline)
    docs = await cursor.to_list(length=100)
    playlists = [
        {
            "id": str(doc["_id"]),
            "name": doc.get("name", ""),
            "description": doc.get("description", ""),
            "track_count": doc.get("track_count", 0),
            "cover_url": doc.get("cover_url", ""),
            "is_public": doc.get("is_public", False),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
        }
        for doc in docs
    ]
    return {"playlists": playlists}


@router.get("/{playlist_id}", summary="Get playlist details")
async def get_playlist(
    playlist_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    p_oid = to_object_id(playlist_id, "Playlist")
    user_oid = to_object_id(user["_id"], "User")
    doc = await db.playlists.find_one({
        "_id": p_oid,
        "user_id": user_oid,
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Playlist not found")
    tracks = doc.get("tracks", [])
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "tracks": tracks,
        "track_count": doc.get("track_count") if doc.get("track_count") is not None else len(tracks),
        "cover_url": doc.get("cover_url", ""),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@router.put("/{playlist_id}", summary="Update playlist")
async def update_playlist(
    playlist_id: str,
    data: PlaylistUpdate,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    p_oid = to_object_id(playlist_id, "Playlist")
    user_oid = to_object_id(user["_id"], "User")

    update = {"updated_at": datetime.now(timezone.utc)}
    if data.name is not None:
        update["name"] = data.name
    if data.description is not None:
        update["description"] = data.description

    result = await db.playlists.update_one(
        {"_id": p_oid, "user_id": user_oid},
        {"$set": update},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"message": "Playlist updated"}


@router.delete("/{playlist_id}", summary="Delete playlist")
async def delete_playlist(
    playlist_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    p_oid = to_object_id(playlist_id, "Playlist")
    user_oid = to_object_id(user["_id"], "User")

    result = await db.playlists.delete_one({
        "_id": p_oid,
        "user_id": user_oid,
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"message": "Playlist deleted"}


@router.post("/{playlist_id}/tracks", summary="Add track to playlist")
async def add_track(
    playlist_id: str,
    data: AddTrackRequest,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    p_oid = to_object_id(playlist_id, "Playlist")
    user_oid = to_object_id(user["_id"], "User")

    now = datetime.now(timezone.utc)
    track = {
        "video_id": data.video_id,
        "title": data.title,
        "artist": data.artist,
        "duration": data.duration,
        "thumbnail": data.thumbnail,
        "added_at": now,
    }
    result = await db.playlists.update_one(
        {"_id": p_oid, "user_id": user_oid},
        {
            "$push": {"tracks": track},
            "$inc": {"track_count": 1},
            "$set": {"updated_at": now},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Conditionally set cover_url atomically if currently empty
    if data.thumbnail:
        await db.playlists.update_one(
            {
                "_id": p_oid,
                "user_id": user_oid,
                "$or": [{"cover_url": ""}, {"cover_url": None}, {"cover_url": {"$exists": False}}],
            },
            {"$set": {"cover_url": data.thumbnail}},
        )

    return {"message": "Track added to playlist"}


@router.delete("/{playlist_id}/tracks/{video_id}", summary="Remove track from playlist")
async def remove_track(
    playlist_id: str,
    video_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    p_oid = to_object_id(playlist_id, "Playlist")
    user_oid = to_object_id(user["_id"], "User")
    now = datetime.now(timezone.utc)

    result = await db.playlists.update_one(
        {"_id": p_oid, "user_id": user_oid},
        {
            "$pull": {"tracks": {"video_id": video_id}},
            "$inc": {"track_count": -1},
            "$set": {"updated_at": now},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Ensure track_count does not drop below 0
    await db.playlists.update_one(
        {"_id": p_oid, "user_id": user_oid, "track_count": {"$lt": 0}},
        {"$set": {"track_count": 0}},
    )

    return {"message": "Track removed from playlist"}
