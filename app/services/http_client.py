"""
Persistent HTTP Client Pool.
Provides shared httpx.AsyncClient instances with connection pooling and keepalive
to eliminate repetitive TCP/TLS handshake overhead across streaming, lyrics, and YouTube APIs.
"""

import httpx
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_shared_client: Optional[httpx.AsyncClient] = None
_stream_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create the shared general-purpose AsyncClient with connection pooling."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=50,
                max_connections=100,
                keepalive_expiry=60.0,
            ),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
    return _shared_client


def get_stream_client() -> httpx.AsyncClient:
    """Get or create the high-throughput streaming AsyncClient for audio proxying."""
    global _stream_client
    if _stream_client is None or _stream_client.is_closed:
        _stream_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=15.0),
            limits=httpx.Limits(
                max_keepalive_connections=30,
                max_connections=60,
                keepalive_expiry=90.0,
            ),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
    return _stream_client


async def close_http_clients() -> None:
    """Gracefully close all shared HTTP clients on application shutdown."""
    global _shared_client, _stream_client
    if _shared_client is not None and not _shared_client.is_closed:
        try:
            await _shared_client.aclose()
            logger.info("Closed shared HTTP client pool")
        except Exception as e:
            logger.warning(f"Error closing shared HTTP client: {e}")
        _shared_client = None

    if _stream_client is not None and not _stream_client.is_closed:
        try:
            await _stream_client.aclose()
            logger.info("Closed streaming HTTP client pool")
        except Exception as e:
            logger.warning(f"Error closing stream HTTP client: {e}")
        _stream_client = None

