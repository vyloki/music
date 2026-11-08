"""
Wave - Security Utilities
Password hashing (bcrypt), JWT token creation/validation, and auth dependencies.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.database import get_db
from app.utils.db import to_object_id
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

# --- Password Hashing (Direct native bcrypt for Python 3.13 compatibility) ---

def _hash_worker(password: str) -> str:
    """Worker function for bcrypt hashing with rounds=11."""
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 72:
        raise ValueError("Password cannot exceed 72 bytes")
    salt = bcrypt.gensalt(rounds=11)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def _verify_worker(plain_password: str, hashed_password: str) -> bool:
    """Worker function for bcrypt verification."""
    try:
        pwd_bytes = plain_password.encode("utf-8")
        if len(pwd_bytes) > 72:
            return False
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash a password using bcrypt (synchronous)."""
    return _hash_worker(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash (synchronous)."""
    return _verify_worker(plain_password, hashed_password)


async def hash_password_async(password: str) -> str:
    """Hash a password asynchronously using asyncio.to_thread to avoid blocking the event loop."""
    return await asyncio.to_thread(_hash_worker, password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password asynchronously using asyncio.to_thread."""
    return await asyncio.to_thread(_verify_worker, plain_password, hashed_password)


# --- JWT Token Management ---

def create_access_token(
    user_id: str,
    username: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload = {
        "sub": user_id,
        "username": username,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )


def create_refresh_token(
    user_id: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT refresh token (longer lived)."""
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(days=settings.jwt_refresh_token_expire_days)
    )
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- Auth Dependency (Route Protection) ---

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        security_scheme
    ),
    db=Depends(get_db)
) -> dict:
    """
    FastAPI dependency to extract and validate the current user from JWT.
    Use this on any route that requires authentication.

    Usage:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            return {"user_id": user["_id"]}
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_token(token)

    # Verify this is an access token (not a refresh token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id = payload.get("sub")
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable",
        )

    # Fetch user from database
    user = await db.users.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Convert ObjectId to string for serialization
    user["_id"] = str(user["_id"])
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        security_scheme
    ),
    db=Depends(get_db)
) -> Optional[dict]:
    """
    Optional auth dependency — returns user if authenticated, None otherwise.
    Use for routes that work with or without authentication.
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None
