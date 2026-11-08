"""
Wave - Authentication Routes
User registration, login, token refresh, and profile management.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import Optional, Dict, Any
from app.database import get_db
from app.models.user import (
    UserRegister,
    UserLogin,
    UserProfileUpdate,
    UserResponse,
    TokenResponse,
    RefreshTokenRequest,
    MessageResponse,
)
from app.utils.security import (
    hash_password,
    verify_password,
    hash_password_async,
    verify_password_async,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.services.youtube_service import get_video_info
from app.config import settings
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.utils.db import to_object_id
from datetime import datetime, timezone
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def user_to_response(user: dict) -> UserResponse:
    """Convert a MongoDB user document to a UserResponse model."""
    return UserResponse(
        id=str(user["_id"]),
        username=user["username"],
        email=user["email"],
        display_name=user.get("display_name"),
        avatar_url=user.get("avatar_url"),
        created_at=user.get("created_at"),
        liked_tracks=user.get("liked_tracks", []),
        settings=user.get("settings", {
            "theme": "sand",
            "quality": "high",
            "language_preference": []
        }),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user"
)
async def register(data: UserRegister, db=Depends(get_db)):
    """
    Register a new user account.

    - Validates email uniqueness
    - Validates username uniqueness
    - Hashes password with bcrypt
    - Returns JWT access + refresh tokens
    """
    # Check if email already exists
    existing_email = await db.users.find_one({"email": data.email})
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    # Check if username already exists
    existing_username = await db.users.find_one({"username": data.username})
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken"
        )

    # Hash password asynchronously
    password_hash = await hash_password_async(data.password)

    # Create user document
    now = datetime.now(timezone.utc)
    user_doc = {
        "username": data.username,
        "email": data.email,
        "password_hash": password_hash,
        "display_name": data.display_name or data.username,
        "avatar_url": None,
        "created_at": now,
        "updated_at": now,
        "liked_tracks": [],
        "liked_songs": [],
        "settings": {
            "theme": "sand",
            "quality": "high",
            "language_preference": []
        }
    }

    # Insert into MongoDB
    try:
        result = await db.users.insert_one(user_doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered"
        )
    user_doc["_id"] = result.inserted_id

    logger.info(f"✅ New user registered: {data.username} ({data.email})")

    # Generate tokens
    user_id = str(result.inserted_id)
    access_token = create_access_token(user_id, data.username)
    refresh_token = create_refresh_token(user_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=user_to_response(user_doc),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password"
)
async def login(data: UserLogin, db=Depends(get_db)):
    """
    Authenticate a user with email and password.
    Returns JWT access + refresh tokens on success.
    """
    # Find user by email
    user = await db.users.find_one({"email": data.email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Verify password asynchronously
    if not await verify_password_async(data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    logger.info(f"✅ User logged in: {user['username']}")

    # Generate tokens
    user_id = str(user["_id"])
    access_token = create_access_token(user_id, user["username"])
    refresh_token = create_refresh_token(user_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=user_to_response(user),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh an expired access token"
)
async def refresh_token(data: RefreshTokenRequest, db=Depends(get_db)):
    """
    Use a valid refresh token to get a new access token.
    Rotates the refresh token and invalidates the previous one.
    """
    # Decode the refresh token
    payload = decode_token(data.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type — expected refresh token"
        )

    user_id = payload.get("sub")
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier"
        )

    # Check if token was revoked
    if db is not None:
        revoked = await db.revoked_tokens.find_one({"token": data.refresh_token})
        if revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has been revoked"
            )

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # Revoke old refresh token (Token rotation)
    if db is not None:
        try:
            await db.revoked_tokens.insert_one({
                "token": data.refresh_token,
                "user_id": user_id,
                "revoked_at": datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.debug(f"Revoke token note: {e}")

    # Generate new tokens
    new_access_token = create_access_token(
        str(user["_id"]),
        user["username"]
    )
    new_refresh_token = create_refresh_token(str(user["_id"]))

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=user_to_response(user),
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Sign out user and invalidate refresh token"
)
async def logout(data: Optional[RefreshTokenRequest] = None, db=Depends(get_db)):
    """Revoke refresh token on sign out."""
    if data and data.refresh_token and db is not None:
        try:
            await db.revoked_tokens.update_one(
                {"token": data.refresh_token},
                {
                    "$set": {
                        "token": data.refresh_token,
                        "revoked_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
        except Exception:
            pass
    return MessageResponse(message="Successfully signed out")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile"
)
async def get_me(user: dict = Depends(get_current_user)):
    """
    Get the profile of the currently authenticated user.
    Requires a valid JWT access token.
    """
    return user_to_response(user)


@router.put(
    "/profile",
    response_model=UserResponse,
    summary="Update user profile"
)
async def update_profile(
    data: UserProfileUpdate,
    user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Update the current user's profile information.
    Only provided fields will be updated using find_one_and_update in a single query.
    """
    update_fields = {}

    if data.display_name is not None:
        update_fields["display_name"] = data.display_name
    if data.avatar_url is not None:
        update_fields["avatar_url"] = data.avatar_url
    if data.settings is not None:
        # Merge settings (don't replace entirely)
        current_settings = user.get("settings", {})
        if isinstance(current_settings, dict):
            merged_settings = dict(current_settings)
            merged_settings.update(data.settings)
        else:
            merged_settings = data.settings
        update_fields["settings"] = merged_settings

    if update_fields and db is not None:
        update_fields["updated_at"] = datetime.now(timezone.utc)
        updated_user = await db.users.find_one_and_update(
            {"_id": ObjectId(user["_id"])},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER
        )
        if not updated_user:
            updated_user = {**user, **update_fields}
    else:
        updated_user = {**user, **update_fields}

    updated_user["_id"] = str(updated_user["_id"])
    return user_to_response(updated_user)


@router.post(
    "/like/{video_id}",
    summary="Toggle like on a track"
)
async def toggle_like(
    video_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """Toggle like/unlike on a track with full track metadata preservation."""
    liked_tracks = user.get("liked_tracks", [])
    liked_songs = user.get("liked_songs", [])
    user_id_str = str(user["_id"])
    track_data = body.get("track") if (body and isinstance(body, dict)) else None

    is_currently_liked = (
        video_id in liked_tracks or
        video_id in liked_songs or
        (isinstance(liked_songs, list) and any(isinstance(item, dict) and item.get("video_id") == video_id for item in liked_songs))
    )

    if is_currently_liked:
        # Unlike
        await db.users.update_one(
            {"_id": ObjectId(user["_id"])},
            {
                "$pull": {
                    "liked_tracks": video_id,
                    "liked_songs": video_id,
                }
            }
        )
        if isinstance(liked_songs, list) and any(isinstance(item, dict) for item in liked_songs):
            await db.users.update_one(
                {"_id": ObjectId(user["_id"])},
                {"$pull": {"liked_songs": {"video_id": video_id}}}
            )
        if db is not None:
            await db.liked_songs.delete_one({"user_id": user_id_str, "video_id": video_id})
        return {"status": "unliked", "is_liked": False, "message": "Track unliked"}
    else:
        # Like
        await db.users.update_one(
            {"_id": ObjectId(user["_id"])},
            {
                "$addToSet": {
                    "liked_tracks": video_id,
                    "liked_songs": video_id,
                }
            }
        )
        if db is not None:
            # If track_data was not sent, check song_cache or stream_cache
            if not track_data:
                cached = await db.song_cache.find_one({"video_id": video_id})
                if not cached:
                    cached = await db.song_cache.find_one({"_id": video_id})
                if cached:
                    track_data = cached
                else:
                    stream_cached = await db.stream_cache.find_one({"_id": video_id})
                    if stream_cached:
                        track_data = stream_cached

            title = (track_data.get("title") or track_data.get("track_name") or "Liked Song") if track_data else "Liked Song"
            artist = (track_data.get("artist") or "") if track_data else ""
            movie = (track_data.get("movie") or "") if track_data else ""
            language = (track_data.get("language") or "") if track_data else ""
            thumbnail = (track_data.get("thumbnail") or track_data.get("album_art") or "") if track_data else ""
            duration = int((track_data.get("duration") or 0)) if track_data else 0
            is_extracted = bool(track_data.get("is_extracted") or video_id.startswith("ext_")) if track_data else video_id.startswith("ext_")
            platform = (track_data.get("platform") or "YouTube") if track_data else "YouTube"

            song_doc = {
                "user_id": user_id_str,
                "video_id": video_id,
                "title": title,
                "track_name": title,
                "artist": artist,
                "movie": movie,
                "language": language,
                "thumbnail": thumbnail,
                "album_art": thumbnail,
                "duration": duration,
                "is_extracted": is_extracted,
                "platform": platform,
                "track": track_data or {
                    "video_id": video_id,
                    "title": title,
                    "artist": artist,
                    "movie": movie,
                    "language": language,
                    "thumbnail": thumbnail,
                    "duration": duration,
                    "is_extracted": is_extracted,
                    "platform": platform
                },
                "liked_at": datetime.now(timezone.utc),
            }

            await db.liked_songs.update_one(
                {"user_id": user_id_str, "video_id": video_id},
                {"$set": song_doc},
                upsert=True
            )

        return {"status": "liked", "is_liked": True, "message": "Track liked"}


@router.delete(
    "/like/{video_id}",
    summary="Unlike a track"
)
async def unlike_track(
    video_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Unlike a track using standard DELETE REST method.
    Pulls track from user's liked collections using $pull and removes from liked_songs.
    """
    user_id_str = str(user["_id"])
    if db is not None:
        await db.users.update_one(
            {"_id": ObjectId(user["_id"])},
            {
                "$pull": {
                    "liked_songs": video_id,
                    "liked_tracks": video_id,
                }
            }
        )
        liked_songs_list = user.get("liked_songs", [])
        if isinstance(liked_songs_list, list) and any(isinstance(item, dict) for item in liked_songs_list):
            await db.users.update_one(
                {"_id": ObjectId(user["_id"])},
                {"$pull": {"liked_songs": {"video_id": video_id}}}
            )
        await db.liked_songs.delete_one({"user_id": user_id_str, "video_id": video_id})

    return {"status": "unliked", "is_liked": False, "message": "Track unliked"}


@router.get(
    "/liked",
    summary="Get all liked tracks"
)
async def get_liked_tracks(
    user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Retrieve full track objects for all liked songs of the user.
    Eliminates N+1 sequential fetches:
    - Partitions liked items into full objects vs string video IDs.
    - Queries song_cache with db.song_cache.find({"video_id": {"$in": string_ids}}) in ONE single query.
    - Concurrently fetches remaining IDs with asyncio.gather.
    """
    user_id_str = str(user["_id"])
    if db is None:
        return {"tracks": [], "total": 0}

    tracks = []
    seen_ids = set()

    # 1. Lookup from liked_songs collection (instant, preserved metadata)
    cursor = db.liked_songs.find({"user_id": user_id_str}).sort("liked_at", -1)
    docs = await cursor.to_list(200)

    for doc in docs:
        vid = doc.get("video_id")
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            t = doc.get("track") or doc
            t["video_id"] = vid
            t["title"] = doc.get("title") or t.get("title") or "Liked Song"
            t["track_name"] = t["title"]
            t["artist"] = doc.get("artist") or t.get("artist") or ""
            t["movie"] = doc.get("movie") or t.get("movie") or ""
            t["language"] = doc.get("language") or t.get("language") or ""
            t["thumbnail"] = doc.get("thumbnail") or t.get("thumbnail") or ""
            t["album_art"] = t["thumbnail"]
            t["duration"] = doc.get("duration") or t.get("duration") or 0
            t["is_extracted"] = doc.get("is_extracted") or vid.startswith("ext_")
            t["is_liked"] = True
            tracks.append(t)

    # 2. Partition user-level liked items into full objects vs string video IDs
    raw_user_liked = []
    for key in ("liked_songs", "liked_tracks"):
        val = user.get(key)
        if isinstance(val, list):
            for item in val:
                if item is not None and item not in raw_user_liked:
                    raw_user_liked.append(item)

    full_objects = []
    string_ids = []

    for item in raw_user_liked:
        if isinstance(item, dict):
            vid = item.get("video_id") or item.get("id")
            if vid:
                vid = str(vid)
                if vid not in seen_ids:
                    seen_ids.add(vid)
                    t = dict(item)
                    t["video_id"] = vid
                    t["is_liked"] = True
                    full_objects.append(t)
        elif isinstance(item, str) and item.strip():
            vid = item.strip()
            if vid not in seen_ids and vid not in string_ids:
                string_ids.append(vid)

    tracks.extend(full_objects)

    # 3. For string video IDs, query song_cache in ONE single query
    if string_ids:
        cached_map = {}
        cursor = db.song_cache.find({"video_id": {"$in": string_ids}})
        cached_docs = await cursor.to_list(len(string_ids) + 10)
        for c in cached_docs:
            vid = c.get("video_id") or c.get("_id")
            if vid:
                c.pop("_id", None)
                c["video_id"] = str(vid)
                c["is_liked"] = True
                cached_map[str(vid)] = c

        # 4. If any remaining IDs are not in song_cache, fetch concurrently with asyncio.gather
        remaining_ids = [vid for vid in string_ids if vid not in cached_map]

        if remaining_ids:
            async def _fetch_single_track(vid: str) -> dict:
                try:
                    if not vid.startswith("ext_"):
                        info = await get_video_info(vid)
                        if info and isinstance(info, dict):
                            info.pop("_id", None)
                            info["video_id"] = vid
                            info["is_liked"] = True
                            return info
                    else:
                        stream_cached = await db.stream_cache.find_one({"_id": vid})
                        if stream_cached:
                            return {
                                "video_id": vid,
                                "title": stream_cached.get("title") or "Liked Audio",
                                "track_name": stream_cached.get("title") or "Liked Audio",
                                "artist": stream_cached.get("artist") or "",
                                "thumbnail": stream_cached.get("thumbnail") or "",
                                "album_art": stream_cached.get("thumbnail") or "",
                                "duration": stream_cached.get("duration", 0),
                                "is_extracted": True,
                                "is_liked": True,
                            }
                except Exception as e:
                    logger.warning(f"Error fetching track info for {vid}: {e}")

                return {
                    "video_id": vid,
                    "title": "Liked Song",
                    "track_name": "Liked Song",
                    "artist": "",
                    "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if not vid.startswith("ext_") else "",
                    "album_art": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if not vid.startswith("ext_") else "",
                    "duration": 0,
                    "is_extracted": vid.startswith("ext_"),
                    "is_liked": True,
                }

            fetched_tracks = await asyncio.gather(*[_fetch_single_track(vid) for vid in remaining_ids])
            for t in fetched_tracks:
                cached_map[t["video_id"]] = t

        for vid in string_ids:
            if vid in cached_map and vid not in seen_ids:
                seen_ids.add(vid)
                tracks.append(cached_map[vid])

    return {"tracks": tracks, "total": len(tracks)}
