"""
Wave - Link Audio Extractor Service
Extracts exact audio from URLs (YouTube, Instagram, Twitter/X, TikTok, Reddit, etc.)
and matches full-length original songs via smart search.
"""

import yt_dlp
import asyncio
import logging
import re
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from app.services.youtube_service import _parse_track_metadata, search_youtube
from app.database import database

logger = logging.getLogger(__name__)

# yt-dlp configuration for link audio extraction
EXTRACT_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "format": "bestaudio/best",
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "ios", "web"]
        },
        "instagram": {
            "api": "graphql"
        }
    },
    "ignoreerrors": False,
    "no_color": True,
    "socket_timeout": 20,
}


def _detect_platform(url: str, extractor_name: str = "") -> str:
    """Identify the platform name from URL or yt-dlp extractor."""
    url_lower = url.lower()
    ext_lower = extractor_name.lower()

    if "youtube.com/shorts" in url_lower or "youtu.be" in url_lower and "shorts" in url_lower:
        return "YouTube Short"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"
    elif "instagram.com/reel" in url_lower:
        return "Instagram Reel"
    elif "instagram.com" in url_lower:
        return "Instagram"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "Twitter / X"
    elif "tiktok.com" in url_lower:
        return "TikTok"
    elif "reddit.com" in url_lower:
        return "Reddit"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "Facebook"
    elif "soundcloud.com" in url_lower:
        return "SoundCloud"
    elif "vimeo.com" in url_lower:
        return "Vimeo"
    
    if ext_lower:
        return ext_lower.capitalize()
    return "Web Link"


def _generate_extraction_id(url: str) -> str:
    """Generate a clean unique extraction ID from URL."""
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    return f"ext_{h}"


async def extract_from_url(
    url: str,
    mode: str = "same",
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract audio information from a URL.
    Modes:
      - 'same': Extracts the exact clip audio and duration from the given link.
      - 'original': Identifies the song in the clip and finds the full-length studio track on YouTube.
    """
    if not url or not url.strip():
        return {
            "success": False,
            "error": "Please provide a valid URL."
        }

    clean_url = url.strip()
    # Basic URL schema validation
    if not re.match(r"^https?://", clean_url, flags=re.IGNORECASE):
        clean_url = f"https://{clean_url}"

    extraction_id = _generate_extraction_id(clean_url)
    db = database.db

    # === STEP 1: EXTRACT INFO VIA YT-DLP ===
    def _run_ytdlp():
        try:
            with yt_dlp.YoutubeDL(EXTRACT_OPTS) as ydl:
                info = ydl.extract_info(clean_url, download=False)
                return info
        except yt_dlp.utils.DownloadError as de:
            logger.warning(f"yt-dlp download error for {clean_url}: {de}")
            msg = str(de)
            if "private" in msg.lower():
                return {"_error": "This post/video is private or restricted."}
            elif "not found" in msg.lower() or "404" in msg.lower():
                return {"_error": "The media was not found or has been deleted."}
            elif "login" in msg.lower():
                return {"_error": "This content requires a login to view."}
            return {"_error": "Could not extract audio from this link. Make sure the link is public and valid."}
        except Exception as e:
            logger.warning(f"Extraction error for {clean_url}: {e}")
            return {"_error": f"Extraction failed: {str(e)}"}

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, _run_ytdlp)

    if not info or info.get("_error"):
        error_msg = info.get("_error") if isinstance(info, dict) else "Could not extract audio from this link."
        return {
            "success": False,
            "error": error_msg
        }

    # Handle playlist or multiple entries if returned
    if "entries" in info and isinstance(info["entries"], list):
        entries = [e for e in info["entries"] if e]
        if entries:
            info = entries[0]

    raw_title = info.get("title") or "Extracted Audio"
    uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""
    duration = int(info.get("duration") or 0)
    extractor = info.get("extractor") or ""
    platform = _detect_platform(clean_url, extractor)

    # Resolve direct audio stream URL
    stream_url = info.get("url")
    if not stream_url and info.get("formats"):
        # Select best audio format
        audio_formats = [
            f for f in info["formats"]
            if f.get("vcodec") == "none" or (f.get("acodec") and f.get("acodec") != "none")
        ]
        if audio_formats:
            # Sort by audio bitrate
            audio_formats.sort(key=lambda f: f.get("abr") or 0, reverse=True)
            stream_url = audio_formats[0].get("url")
        else:
            stream_url = info["formats"][-1].get("url")

    # Resolve thumbnail
    thumbnail = info.get("thumbnail") or ""
    if not thumbnail and info.get("thumbnails"):
        thumbs = info["thumbnails"]
        if isinstance(thumbs, list) and len(thumbs) > 0:
            thumbnail = thumbs[-1].get("url") or ""

    # Parse clean metadata
    meta = _parse_track_metadata(raw_title, uploader)
    clean_title = meta.get("title") or raw_title
    movie = meta.get("movie") or ""
    language = meta.get("language") or ""
    artist = meta.get("artist") or uploader or "Unknown Artist"

    # === STEP 2: MODE PROCESSING ===
    yt_id = info.get("id") if (platform in ["YouTube", "YouTube Short"] and info.get("id")) else None
    chosen_video_id = yt_id or extraction_id

    if mode == "original":
        # Check if the extracted media is already a full-length song (> 150s)
        if duration >= 150 and platform in ["YouTube", "YouTube Short"]:
            final_track = {
                "video_id": chosen_video_id,
                "title": clean_title,
                "track_name": clean_title,
                "artist": artist,
                "movie": movie,
                "language": language,
                "thumbnail": thumbnail,
                "album_art": thumbnail,
                "duration": duration,
                "platform": platform,
                "source_url": clean_url,
                "mode": "original",
                "matched_original": False,
                "is_extracted": True,
            }
        else:
            # Short clip / Instagram / Twitter / TikTok -> Search for full-length song
            search_query = f"{clean_title} {movie} {artist} full song".strip()
            # Clean noise from search query
            search_query = re.sub(r"[#@][\w_]+", "", search_query).strip()
            search_query = re.sub(r"\s{2,}", " ", search_query)

            matched_tracks = await search_youtube(search_query, max_results=5)
            full_match = None
            if matched_tracks:
                # Prefer matches with duration > 120s
                for t in matched_tracks:
                    if t.get("duration", 0) >= 100:
                        full_match = t
                        break
                if not full_match:
                    full_match = matched_tracks[0]

            if full_match:
                final_track = {
                    "video_id": full_match.get("video_id"),
                    "title": full_match.get("title") or clean_title,
                    "track_name": full_match.get("title") or clean_title,
                    "artist": full_match.get("artist") or artist,
                    "movie": full_match.get("movie") or movie,
                    "language": full_match.get("language") or language,
                    "thumbnail": full_match.get("thumbnail") or thumbnail,
                    "album_art": full_match.get("thumbnail") or thumbnail,
                    "duration": full_match.get("duration") or duration,
                    "platform": platform,
                    "source_url": clean_url,
                    "mode": "original",
                    "matched_original": True,
                    "matched_query": search_query,
                    "is_extracted": False,
                }
            else:
                # Fallback to same audio if no full song match was found
                final_track = {
                    "video_id": chosen_video_id,
                    "title": clean_title,
                    "track_name": clean_title,
                    "artist": artist,
                    "movie": movie,
                    "language": language,
                    "thumbnail": thumbnail,
                    "album_art": thumbnail,
                    "duration": duration,
                    "platform": platform,
                    "source_url": clean_url,
                    "mode": "same",
                    "matched_original": False,
                    "is_extracted": True,
                }
    else:
        # Mode is "same" (exact audio duration)
        final_track = {
            "video_id": chosen_video_id,
            "title": clean_title,
            "track_name": clean_title,
            "artist": artist,
            "movie": movie,
            "language": language,
            "thumbnail": thumbnail,
            "album_art": thumbnail,
            "duration": duration,
            "platform": platform,
            "source_url": clean_url,
            "mode": "same",
            "matched_original": False,
            "is_extracted": True,
        }

    # === STEP 3: CACHE STREAM URL AND SONG METADATA ===
    if db is not None:
        try:
            if stream_url:
                stream_doc = {
                    "stream_url": stream_url,
                    "format": info.get("format", ""),
                    "ext": info.get("ext", "mp4"),
                    "duration": duration,
                    "title": clean_title,
                    "artist": artist,
                    "source_url": clean_url,
                    "cached_at": datetime.now(timezone.utc),
                    "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
                }
                await db.stream_cache.update_one(
                    {"_id": final_track["video_id"]},
                    {"$set": stream_doc},
                    upsert=True
                )
                if final_track["video_id"] != extraction_id:
                    await db.stream_cache.update_one(
                        {"_id": extraction_id},
                        {"$set": stream_doc},
                        upsert=True
                    )

            await db.song_cache.update_one(
                {"_id": final_track["video_id"]},
                {"$set": {**final_track, "cached_at": datetime.now(timezone.utc)}},
                upsert=True
            )
        except Exception as e:
            logger.debug(f"Stream/song cache save error: {e}")

    # === STEP 4: PERSIST EXTRACTION HISTORY ===
    await save_extraction_history(user_id, clean_url, final_track, mode)

    return {
        "success": True,
        "track": final_track,
        "mode": mode,
        "platform": platform,
    }


async def save_extraction_history(
    user_id: Optional[str],
    url: str,
    track: dict,
    mode: str
) -> None:
    """Save extraction to user history in MongoDB."""
    db = database.db
    if db is None:
        return

    try:
        entry = {
            "url": url,
            "title": track.get("title") or "Extracted Audio",
            "artist": track.get("artist") or "",
            "movie": track.get("movie") or "",
            "language": track.get("language") or "",
            "thumbnail": track.get("thumbnail") or "",
            "duration": track.get("duration") or 0,
            "platform": track.get("platform") or "Web Link",
            "mode": mode,
            "track": track,
            "extracted_at": datetime.now(timezone.utc),
        }

        if user_id:
            entry["user_id"] = user_id
            await db.link_history.update_one(
                {"user_id": user_id, "url": url, "mode": mode},
                {"$set": entry},
                upsert=True
            )
        else:
            entry["session_id"] = "guest"
            await db.link_history.update_one(
                {"session_id": "guest", "url": url, "mode": mode},
                {"$set": entry},
                upsert=True
            )
    except Exception as e:
        logger.debug(f"Failed to save link history: {e}")


async def get_extraction_history(
    user_id: Optional[str] = None,
    limit: int = 20,
    projection: Optional[dict] = None,
) -> List[dict]:
    """Retrieve extraction history for a user."""
    db = database.db
    if db is None:
        return []

    try:
        query = {"user_id": user_id} if user_id else {"session_id": "guest"}
        cursor = db.link_history.find(query, projection).sort("extracted_at", -1).limit(limit)
        items = await cursor.to_list(limit)

        result = []
        for item in items:
            track = item.get("track")
            if isinstance(track, dict):
                # Omit any large format metadata or raw payloads from history listing
                track = {k: v for k, v in track.items() if k not in ("formats", "raw_info", "thumbnails")}
            result.append({
                "id": str(item.get("_id")),
                "url": item.get("url"),
                "title": item.get("title"),
                "artist": item.get("artist"),
                "movie": item.get("movie"),
                "language": item.get("language"),
                "thumbnail": item.get("thumbnail"),
                "duration": item.get("duration", 0),
                "platform": item.get("platform", "Web Link"),
                "mode": item.get("mode", "same"),
                "track": track,
                "extracted_at": item.get("extracted_at").isoformat() if item.get("extracted_at") else "",
            })
        return result
    except Exception as e:
        logger.debug(f"Failed to get link history: {e}")
        return []


async def delete_extraction_history(
    item_id: str,
    user_id: Optional[str] = None
) -> bool:
    """Delete a single extraction history item."""
    from bson import ObjectId
    db = database.db
    if db is None:
        return False

    try:
        query = {"_id": ObjectId(item_id)}
        if user_id:
            query["user_id"] = user_id
        res = await db.link_history.delete_one(query)
        return res.deleted_count > 0
    except Exception as e:
        logger.debug(f"Failed to delete history item: {e}")
        return False


async def clear_extraction_history(
    user_id: Optional[str] = None
) -> bool:
    """Clear all extraction history for a user."""
    db = database.db
    if db is None:
        return False

    try:
        query = {"user_id": user_id} if user_id else {"session_id": "guest"}
        await db.link_history.delete_many(query)
        return True
    except Exception as e:
        logger.debug(f"Failed to clear history: {e}")
        return False
