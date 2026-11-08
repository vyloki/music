"""
Wave - Playlist Data Models
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class PlaylistTrack(BaseModel):
    """A track within a playlist."""
    video_id: str
    title: str
    artist: str = ""
    duration: int = 0
    thumbnail: str = ""
    added_at: Optional[datetime] = None


class PlaylistCreate(BaseModel):
    """Schema for creating a new playlist."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default="", max_length=300)


class PlaylistUpdate(BaseModel):
    """Schema for updating a playlist."""
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=300)


class PlaylistResponse(BaseModel):
    """Schema for playlist response."""
    id: str
    name: str
    description: str = ""
    track_count: int = 0
    cover_url: str = ""
    is_public: Optional[bool] = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AddTrackRequest(BaseModel):
    """Schema for adding a track to a playlist."""
    video_id: str
    title: str
    artist: str = ""
    duration: int = 0
    thumbnail: str = ""


class HistoryEntry(BaseModel):
    """Schema for recording a play event."""
    video_id: str
    title: str
    artist: str = ""
    thumbnail: str = ""
    duration: Optional[int] = 0
    movie: Optional[str] = ""
    language: Optional[str] = ""
    subtitle: Optional[str] = ""
