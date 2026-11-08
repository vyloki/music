"""
Wave - Stream Routes
Audio streaming endpoints that proxy YouTube audio through our backend.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from app.services.stream_service import get_cached_stream_url, update_stream_cache
from app.services.youtube_service import get_stream_url
from app.services.http_client import get_stream_client
from app.database import database
from app.utils.security import get_optional_user
from datetime import datetime, timezone
import httpx
import re
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream", tags=["Streaming"])

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Optimized streaming buffer chunks
STREAM_CHUNK_SIZE = 262144    # 256KB: Reduces context switching and CPU load during audio playback
DOWNLOAD_CHUNK_SIZE = 524288  # 512KB: High-throughput chunk size for offline file downloads


@router.api_route(
    "/{video_id}",
    methods=["GET", "HEAD"],
    summary="Stream audio for a video"
)
async def stream_audio(
    video_id: str,
    request: Request,
    user: dict = Depends(get_optional_user),
):
    """
    Stream audio from YouTube through our server with seeking, accurate HEAD probing, and auto-token recovery.
    """
    is_head = request.method == "HEAD"
    range_header = request.headers.get("range")
    db = database.db

    # In HEAD /api/stream/{video_id}:
    # If stream info is in cache and contains content_length, return 200 with headers immediately
    # without making an outbound HEAD request to Googlevideo.
    if is_head and db is not None:
        try:
            cached = await db.stream_cache.find_one({
                "_id": video_id,
                "expires_at": {"$gt": datetime.now(timezone.utc)}
            })
            if cached:
                content_length = cached.get("content_length") or cached.get("filesize")
                if content_length:
                    ext = cached.get("ext", "mp4")
                    content_type = "audio/mpeg" if ext == "mp3" else "audio/mp4"
                    return Response(
                        status_code=200,
                        headers={
                            "Accept-Ranges": "bytes",
                            "Cache-Control": "no-cache",
                            "Content-Length": str(content_length),
                        },
                        media_type=content_type,
                    )
        except Exception as e:
            logger.debug(f"Error checking cache for HEAD {video_id}: {e}")

    # Get the stream URL (cached or fresh)
    stream_url = await get_cached_stream_url(video_id)
    if not stream_url:
        raise HTTPException(
            status_code=404,
            detail="Could not extract audio stream"
        )

    # Forward range headers for seeking support
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }

    if range_header:
        headers["Range"] = range_header
    elif is_head:
        # Probe with bytes 0-1 to check existence and retrieve full content length
        headers["Range"] = "bytes=0-1"

    client = get_stream_client()
    try:
        response = await client.send(
            client.build_request("GET", stream_url, headers=headers),
            stream=True,
        )

        # If expired YouTube CDN token (403/404/410), refresh and update stream_cache in DB
        if response.status_code in (403, 404, 410):
            logger.info(f"🔄 Stream URL expired (HTTP {response.status_code}) for {video_id}, refreshing and updating cache...")
            await response.aclose()
            fresh_url = await get_cached_stream_url(video_id, force_refresh=True)
            if fresh_url:
                stream_url = fresh_url
                response = await client.send(
                    client.build_request("GET", stream_url, headers=headers),
                    stream=True,
                )
            else:
                raise HTTPException(
                    status_code=502,
                    detail="Audio stream temporarily unavailable from upstream source"
                )

        if response.status_code >= 400:
            status_code = response.status_code
            await response.aclose()
            raise HTTPException(
                status_code=status_code,
                detail="Upstream streaming error"
            )

        # Determine content type - ensure audio mime-type for mobile background playback
        content_type = response.headers.get("content-type", "audio/mp4")
        if content_type.startswith("video/"):
            content_type = content_type.replace("video/", "audio/")
        elif not content_type.startswith("audio/"):
            content_type = "audio/mp4"

        # Build response headers
        response_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        }

        # Extract content range and total size
        content_range = response.headers.get("content-range")
        total_size = None
        if content_range:
            match = re.search(r"/(\d+)$", content_range)
            if match:
                total_size = match.group(1)
        if not total_size and "content-length" in response.headers:
            total_size = response.headers["content-length"]

        # Persist discovered content length in cache for subsequent HEAD requests
        if total_size and db is not None:
            try:
                await db.stream_cache.update_one(
                    {"_id": video_id},
                    {"$set": {"content_length": int(total_size), "filesize": int(total_size)}}
                )
            except Exception:
                pass

        # Handle HEAD requests accurately (used by mobile Safari/Android for buffer capability probing)
        if is_head:
            await response.aclose()

            if range_header:
                if "content-length" in response.headers:
                    response_headers["Content-Length"] = response.headers["content-length"]
                if content_range:
                    response_headers["Content-Range"] = content_range
                return Response(
                    status_code=206,
                    headers=response_headers,
                    media_type=content_type,
                )
            else:
                if total_size:
                    response_headers["Content-Length"] = total_size

                return Response(
                    status_code=200,
                    headers=response_headers,
                    media_type=content_type,
                )

        if "content-length" in response.headers:
            response_headers["Content-Length"] = response.headers["content-length"]
        if content_range:
            response_headers["Content-Range"] = content_range

        async def stream_generator():
            """Yield audio data in chunks."""
            try:
                async for chunk in response.aiter_bytes(chunk_size=STREAM_CHUNK_SIZE):
                    yield chunk
            except (asyncio.CancelledError, GeneratorExit):
                logger.debug(f"Client disconnected during stream for {video_id}")
            except Exception as e:
                logger.debug(f"Stream iteration note for {video_id}: {e}")
            finally:
                await response.aclose()

        status_code = response.status_code if response.status_code in (200, 206) else (206 if range_header else 200)

        return StreamingResponse(
            stream_generator(),
            status_code=status_code,
            media_type=content_type,
            headers=response_headers,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stream error for {video_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Audio streaming failed"
        )


@router.get(
    "/{video_id}/info",
    summary="Get stream metadata"
)
async def stream_info(video_id: str):
    """Get metadata about the stream (duration, format, etc.), checking cache first."""
    db = database.db
    if db is not None:
        try:
            cached = await db.stream_cache.find_one({
                "_id": video_id,
                "expires_at": {"$gt": datetime.now(timezone.utc)}
            })
            if cached:
                return {
                    "video_id": video_id,
                    "available": True,
                    "format": cached.get("format") or "audio only",
                    "ext": cached.get("ext") or "mp4",
                    "duration": cached.get("duration", 0),
                    "filesize": cached.get("filesize") or cached.get("content_length"),
                }
        except Exception as e:
            logger.debug(f"Error checking cache in stream_info for {video_id}: {e}")

    info = await get_stream_url(video_id)
    if not info:
        raise HTTPException(
            status_code=404,
            detail="Could not get stream info"
        )

    if db is not None:
        try:
            await update_stream_cache(video_id, info)
        except Exception as e:
            logger.debug(f"Cache update error in stream_info: {e}")

    return {
        "video_id": video_id,
        "available": True,
        "format": info.get("format") or "audio only",
        "ext": info.get("ext") or "mp4",
        "duration": info.get("duration", 0),
        "filesize": info.get("filesize") or info.get("content_length"),
    }


@router.get(
    "/{video_id}/download",
    summary="Download audio file"
)
async def download_audio(
    video_id: str,
    title: str = "song",
    artist: str = "artist",
):
    """
    Stream audio with Content-Disposition header so the browser directly downloads it.
    """
    stream_url = await get_cached_stream_url(video_id)
    if not stream_url:
        raise HTTPException(
            status_code=404,
            detail="Could not extract audio stream for download"
        )

    # Sanitize filename
    safe_name = "".join(c for c in f"{artist} - {title}" if c.isalnum() or c in " ._-").strip() or "track"
    filename = f"{safe_name}.mp3"

    client = get_stream_client()
    try:
        response = await client.send(
            client.build_request("GET", stream_url),
            stream=True,
        )

        if response.status_code in (403, 404, 410):
            await response.aclose()
            fresh_url = await get_cached_stream_url(video_id, force_refresh=True)
            if fresh_url:
                stream_url = fresh_url
                response = await client.send(
                    client.build_request("GET", stream_url),
                    stream=True,
                )

        if response.status_code >= 400:
            await response.aclose()
            raise HTTPException(
                status_code=502,
                detail="Unable to fetch audio file from source"
            )

        content_type = response.headers.get("content-type", "audio/mpeg")

        response_headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        }
        if "content-length" in response.headers:
            response_headers["Content-Length"] = response.headers["content-length"]

        async def stream_generator():
            try:
                async for chunk in response.aiter_bytes(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    yield chunk
            except (asyncio.CancelledError, GeneratorExit):
                pass
            finally:
                await response.aclose()

        return StreamingResponse(
            stream_generator(),
            media_type=content_type,
            headers=response_headers,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download stream error for {video_id}: {e}")
        raise HTTPException(status_code=500, detail="Download failed")
