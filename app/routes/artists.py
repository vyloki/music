"""
Wave - Artists API Routes
Provides featured artists, artist profiles, top tracks, and artist search.
"""

from fastapi import APIRouter, HTTPException, Query
from app.services import youtube_service
from app.database import database
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/artists", tags=["Artists"])

# Curated Popular Artists across Telugu, Tamil, Hindi, Punjabi, English
FEATURED_ARTISTS = [
    {
        "id": "arijit-singh",
        "name": "Arijit Singh",
        "genre": "Bollywood / Romantic",
        "image": "https://cdn-images.dzcdn.net/images/artist/ac5350cff290edd5b69fa584b8b1bd4f/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Hindi", "Telugu", "Bengali", "Tamil"],
        "default_language": "Hindi",
    },
    {
        "id": "sid-sriram",
        "name": "Sid Sriram",
        "genre": "Telugu / Tamil Melodies",
        "image": "https://cdn-images.dzcdn.net/images/artist/fbe3e1d17fc6958e047f011f74233f82/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Telugu", "Tamil", "Malayalam", "Hindi", "Kannada"],
        "default_language": "Telugu",
    },
    {
        "id": "anirudh-ravichander",
        "name": "Anirudh Ravichander",
        "genre": "Rock / Electronic / Tamil",
        "image": "https://cdn-images.dzcdn.net/images/artist/9da0a547b39e99bc35c6a9724aef91bf/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Tamil", "Telugu", "Hindi"],
        "default_language": "Tamil",
    },
    {
        "id": "ar-rahman",
        "name": "A.R. Rahman",
        "genre": "World / Classical / Film",
        "image": "https://cdn-images.dzcdn.net/images/artist/bd34315ef977a62a9e28c1ab19bb8ac4/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Tamil", "Hindi", "Telugu", "English"],
        "default_language": "Tamil",
    },
    {
        "id": "shreya-ghoshal",
        "name": "Shreya Ghoshal",
        "genre": "Melody / Classical",
        "image": "https://cdn-images.dzcdn.net/images/artist/3bb832d37d10ff2affcfa9afdc7c68a0/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Hindi", "Telugu", "Tamil", "Bengali", "Kannada", "Malayalam"],
        "default_language": "Hindi",
    },
    {
        "id": "taylor-swift",
        "name": "Taylor Swift",
        "genre": "Pop / Country",
        "image": "https://cdn-images.dzcdn.net/images/artist/e528e270424103b527f8a27ac625563b/500x500-000000-80-0-0.jpg",
        "languages": ["All", "English"],
        "default_language": "English",
    },
    {
        "id": "spb",
        "name": "S.P. Balasubrahmanyam",
        "genre": "Legendary Classics",
        "image": "https://cdn-images.dzcdn.net/images/artist/e1ae356e308e1baad481b84dfe9d05fe/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Telugu", "Tamil", "Kannada", "Hindi", "Malayalam"],
        "default_language": "Telugu",
    },
    {
        "id": "diljit-dosanjh",
        "name": "Diljit Dosanjh",
        "genre": "Punjabi Pop / Folk",
        "image": "https://cdn-images.dzcdn.net/images/artist/79b85e695e0ca6529e56bf3b628e92bd/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Punjabi", "Hindi"],
        "default_language": "Punjabi",
    },
    {
        "id": "devi-sri-prasad",
        "name": "Devi Sri Prasad",
        "genre": "High Voltage Beats / Telugu",
        "image": "https://cdn-images.dzcdn.net/images/artist/abd95cd3882021d0f16006cc391f993c/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Telugu", "Tamil", "Hindi"],
        "default_language": "Telugu",
    },
    {
        "id": "thaman-s",
        "name": "Thaman S",
        "genre": "Telugu / Tamil Blockbusters",
        "image": "https://cdn-images.dzcdn.net/images/artist/f42d76b5c7e4e5dcb1afb373321f16c4/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Telugu", "Tamil", "Hindi"],
        "default_language": "Telugu",
    },
    {
        "id": "sonu-nigam",
        "name": "Sonu Nigam",
        "genre": "Bollywood / Melodies",
        "image": "https://cdn-images.dzcdn.net/images/artist/812220125c4f0db57050438b65afcf78/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Hindi", "Kannada", "Telugu", "Bengali"],
        "default_language": "Hindi",
    },
    {
        "id": "ks-chithra",
        "name": "K.S. Chithra",
        "genre": "Nightingale of South / Melody",
        "image": "https://cdn-images.dzcdn.net/images/artist/b955b3207b61e722cf4d63ee0c762b12/500x500-000000-80-0-0.jpg",
        "languages": ["All", "Telugu", "Tamil", "Malayalam", "Kannada", "Hindi"],
        "default_language": "Telugu",
    },
]


@router.get("/featured", response_model=List[dict])
async def get_featured_artists():
    """Get curated list of popular artists."""
    return FEATURED_ARTISTS


@router.get("/{artist_name}")
async def get_artist_profile(
    artist_name: str,
    language: Optional[str] = Query(default=None, description="Filter songs by language"),
    limit: int = Query(default=30, ge=5, le=50),
):
    """
    Get artist profile and individual hit tracks.
    Filters out long compilations/jukeboxes.
    Supports language-based querying.
    """
    if not artist_name or len(artist_name.strip()) == 0:
        raise HTTPException(status_code=400, detail="Artist name is required")

    artist_clean = artist_name.strip()

    # Match featured artist image and language capabilities
    matched_image = ""
    matched_genre = "Popular Artist"
    available_languages = ["All", "Telugu", "Tamil", "Hindi", "English"]

    for a in FEATURED_ARTISTS:
        if a["name"].lower() == artist_clean.lower() or a["id"] == artist_clean.lower().replace(" ", "-"):
            matched_image = a["image"]
            matched_genre = a["genre"]
            artist_clean = a["name"]
            available_languages = a.get("languages", available_languages)
            break

    lang_filter = (language or "").strip()
    if lang_filter.lower() == "all":
        lang_filter = ""

    # Cache key
    cache_key = f"artist_tracks_{artist_clean.lower()}_{lang_filter.lower()}"
    if database.db is not None:
        cached = await database.db.cache.find_one({"key": cache_key})
        if cached and "tracks" in cached and len(cached["tracks"]) > 0:
            return {
                "artist": artist_clean,
                "genre": matched_genre,
                "image": matched_image or (cached["tracks"][0].get("thumbnail") if cached["tracks"] else ""),
                "languages": available_languages,
                "selected_language": language or "All",
                "total_tracks": len(cached["tracks"]),
                "tracks": cached["tracks"],
            }

    # Fetch individual single songs (strictly avoid jukeboxes / full albums)
    if lang_filter:
        search_queries = [
            f"{artist_clean} {lang_filter} hit songs official audio",
            f"{artist_clean} {lang_filter} latest songs official audio",
            f"{artist_clean} {lang_filter} song official",
        ]
    else:
        search_queries = [
            f"{artist_clean} top hit songs official audio",
            f"{artist_clean} latest songs official audio",
            f"{artist_clean} hit song official",
        ]

    tracks = []
    seen = set()

    for q in search_queries:
        results = await youtube_service.search_youtube(q, max_results=20, filter_mode="song")
        for r in results:
            vid = r.get("video_id")
            if not vid or vid in seen:
                continue

            dur = int(r.get("duration") or 0)
            raw_title = (r.get("title") or r.get("track_name") or "")
            uploader = r.get("artist") or r.get("uploader") or r.get("channel") or ""

            # STRICT SINGLE SONG & OFFICIAL CHANNEL FILTER
            # (exclude > 360s compilations, jukeboxes, albums, unofficial channels)
            if not youtube_service.is_valid_single_song(r):
                continue

            seen.add(vid)
            if not r.get("artist") or r["artist"] == "Unknown Artist":
                r["artist"] = artist_clean
            tracks.append(r)

            if len(tracks) >= limit:
                break
        if len(tracks) >= limit:
            break

    # Sort tracks so verified official music sources rank highest
    tracks.sort(
        key=lambda t: youtube_service.is_official_music_source(
            t.get("artist", "") or t.get("channel", ""), t.get("title", "")
        ),
        reverse=True
    )

    if not matched_image and tracks:
        matched_image = tracks[0].get("thumbnail", "")

    # Cache in DB
    if database.db is not None and tracks:
        try:
            await database.db.cache.update_one(
                {"key": cache_key},
                {"$set": {"key": cache_key, "tracks": tracks}},
                upsert=True,
            )
        except Exception:
            pass

    return {
        "artist": artist_clean,
        "genre": matched_genre,
        "image": matched_image,
        "languages": available_languages,
        "selected_language": language or "All",
        "total_tracks": len(tracks),
        "tracks": tracks,
    }
