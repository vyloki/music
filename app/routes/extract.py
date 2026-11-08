"""
Wave - Link Audio Extractor Routes
Endpoints for extracting audio from links, streaming, downloading, and managing extraction history.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, HttpUrl
from typing import Optional, Literal
import asyncio
import re
import logging
from datetime import datetime, timezone

from app.services.extractor_service import (
    extract_from_url,
    get_extraction_history,
    delete_extraction_history,
    clear_extraction_history,
)
from app.services.http_client import get_stream_client
from app.database import database
from app.utils.security import get_optional_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extract", tags=["Link Extraction"])

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
STREAM_CHUNK_SIZE = 262144    # 256KB buffer for smooth audio streaming
DOWNLOAD_CHUNK_SIZE = 524288  # 512KB buffer for fast bulk downloads

# Projection to retrieve only required fields and omit bulky format/raw metadata arrays
EXTRACTION_HISTORY_PROJECTION = {
    "_id": 1,
    "url": 1,
    "title": 1,
    "artist": 1,
    "movie": 1,
    "language": 1,
    "thumbnail": 1,
    "duration": 1,
    "platform": 1,
    "mode": 1,
    "track": 1,
    "extracted_at": 1,
}


class ExtractRequest(BaseModel):
    url: str
    mode: Literal["same", "original"] = "same"


@router.post("", summary="Extract audio or match full song from URL")
async def extract_audio_endpoint(
    req: ExtractRequest,
    user: Optional[dict] = Depends(get_optional_user),
):
    """
    Extract audio or match original full song from YouTube, Instagram, Twitter/X, TikTok, Reddit, etc.
    Modes:
      - 'same': Extracts exact audio clip of the link.
      - 'original': Searches and matches the full-length studio track.
    """
    user_id = str(user["_id"]) if user and "_id" in user else None
    result = await extract_from_url(req.url, req.mode, user_id)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Could not extract audio from this link.")
        )

    return result


@router.get("/history", summary="Get link extraction history")
async def get_history_endpoint(
    limit: int = 20,
    user: Optional[dict] = Depends(get_optional_user),
):
    """Get the user's past link extraction history with optimized field projection."""
    user_id = str(user["_id"]) if user and "_id" in user else None
    history = await get_extraction_history(user_id, limit, projection=EXTRACTION_HISTORY_PROJECTION)
    return {"history": history, "total": len(history)}


@router.delete("/history/{item_id}", summary="Delete single history item")
async def delete_history_endpoint(
    item_id: str,
    user: Optional[dict] = Depends(get_optional_user),
):
    """Delete a single extraction record from history."""
    user_id = str(user["_id"]) if user and "_id" in user else None
    success = await delete_extraction_history(item_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="History item not found")
    return {"status": "deleted", "id": item_id}


@router.delete("/history", summary="Clear all extraction history")
async def clear_history_endpoint(
    user: Optional[dict] = Depends(get_optional_user),
):
    """Clear all extraction history for the current user."""
    if not user or "_id" not in user:
        return {"status": "cleared"}
    user_id = str(user["_id"])
    await clear_extraction_history(user_id)
    return {"status": "cleared"}


@router.api_route("/stream/{extraction_id}", methods=["GET", "HEAD"], summary="Stream extracted audio")
async def stream_extracted_media(
    extraction_id: str,
    request: Request,
):
    """
    Proxy stream extracted audio using pooled HTTP client with Range, HEAD, and 256KB chunk streaming.
    """
    db = database.db
    if db is None:
        raise HTTPException(status_code=500, detail="Database not connected")

    cached = await db.stream_cache.find_one({"_id": extraction_id})
    if not cached or not cached.get("stream_url"):
        raise HTTPException(status_code=404, detail="Extracted audio stream not found or expired")

    stream_url = cached["stream_url"]

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header
    elif request.method == "HEAD":
        headers["Range"] = "bytes=0-1"

    client = get_stream_client()
    try:
        response = await client.send(
            client.build_request("GET", stream_url, headers=headers),
            stream=True,
        )

        if response.status_code >= 400:
            await response.aclose()
            raise HTTPException(status_code=response.status_code, detail="Extracted stream source error")

        content_type = response.headers.get("content-type", "audio/mp4")
        if content_type.startswith("video/"):
            content_type = content_type.replace("video/", "audio/")
        elif not content_type.startswith("audio/"):
            content_type = "audio/mp4"

        response_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        }
        if "content-length" in response.headers:
            response_headers["Content-Length"] = response.headers["content-length"]
        if "content-range" in response.headers:
            response_headers["Content-Range"] = response.headers["content-range"]

        # Handle HEAD requests accurately
        if request.method == "HEAD":
            content_range = response.headers.get("content-range")
            await response.aclose()
            if range_header:
                return Response(
                    status_code=206,
                    headers=response_headers,
                    media_type=content_type,
                )
            else:
                total_size = None
                if content_range:
                    match = re.search(r"/(\d+)$", content_range)
                    if match:
                        total_size = match.group(1)
                if not total_size and "content-length" in response.headers:
                    total_size = response.headers["content-length"]
                if total_size:
                    response_headers["Content-Length"] = total_size

                return Response(
                    status_code=200,
                    headers=response_headers,
                    media_type=content_type,
                )

        async def stream_generator():
            try:
                async for chunk in response.aiter_bytes(chunk_size=STREAM_CHUNK_SIZE):
                    yield chunk
            except (asyncio.CancelledError, GeneratorExit):
                pass
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
        logger.error(f"Stream error for {extraction_id}: {e}")
        raise HTTPException(status_code=500, detail="Audio streaming failed")


# Backward compatibility alias
stream_extracted_audio = stream_extracted_media


@router.get("/download/{extraction_id}", summary="Download extracted audio")
async def download_extracted_media(
    extraction_id: str,
    title: str = "extracted_song",
    artist: str = "artist",
):
    """
    Download extracted audio file as an MP3 attachment using pooled HTTP client with 512KB chunk buffer.
    """
    db = database.db
    if db is None:
        raise HTTPException(status_code=500, detail="Database not connected")

    cached = await db.stream_cache.find_one({"_id": extraction_id})
    if not cached or not cached.get("stream_url"):
        raise HTTPException(status_code=404, detail="Extracted audio not found for download")

    stream_url = cached["stream_url"]
    safe_name = "".join(c for c in f"{artist} - {title}" if c.isalnum() or c in " ._-").strip() or "extracted_song"
    filename = f"{safe_name}.mp3"

    client = get_stream_client()
    try:
        response = await client.send(
            client.build_request("GET", stream_url),
            stream=True,
        )

        if response.status_code >= 400:
            await response.aclose()
            raise HTTPException(status_code=502, detail="Unable to fetch extracted audio from source")

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
        logger.error(f"Download error for {extraction_id}: {e}")
        raise HTTPException(status_code=500, detail="Download failed")


# Backward compatibility alias
download_extracted_audio = download_extracted_media
