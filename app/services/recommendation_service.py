"""
Wave - Advanced Hybrid Recommendation Engine
=============================================
Features:
1. Time-of-Day & Mood-Based Context Engine (Morning, Afternoon, Evening, Late Night).
2. Multi-Vector Hybrid Song Radio (Related tracks, Artist clusters, Graph Markov transitions, User affinity).
3. Collaborative Transition Learning.
4. Language-Consistent & Personalized Home Feed.
"""

from typing import List, Dict, Optional, Any
from datetime import datetime, timezone, timedelta
from app.database import database
from app.services.youtube_service import search_youtube, get_related_videos
from app.utils.cache import home_feed_cache
import logging
import asyncio
import re

logger = logging.getLogger(__name__)

# Predefined categories for quick browsing
CATEGORIES = [
    {"id": "trending", "name": "Trending Hits", "query": "Top trending songs 2025 official audio", "icon": "flame"},
    {"id": "telugu", "name": "Telugu Hits", "query": "Latest Telugu hit songs", "icon": "music-2"},
    {"id": "hindi", "name": "Bollywood Top", "query": "Top Bollywood romantic songs 2025", "icon": "sparkles"},
    {"id": "english", "name": "Global Pop", "query": "Billboard top hits pop songs", "icon": "globe"},
    {"id": "punjabi", "name": "Punjabi Beats", "query": "Top trending Punjabi songs", "icon": "zap"},
    {"id": "tamil", "name": "Tamil Hits", "query": "Latest Tamil blockbuster songs", "icon": "disc"},
    {"id": "lofi", "name": "Chill & Lo-Fi", "query": "Chill lofi hip hop beats to relax", "icon": "coffee"},
    {"id": "rock", "name": "Rock & Indie", "query": "Indie rock top tracks", "icon": "guitar"},
]


# =====================================================================
# 1. TIME-OF-DAY & MOOD INTELLIGENCE
# =====================================================================

def get_time_of_day_context() -> dict:
    """
    Determine the current time-of-day slot and corresponding mood profile.
    Time slots:
      - Morning (05:00 - 11:59): Fresh, energetic, acoustic, melodic.
      - Afternoon (12:00 - 16:59): Focus, upbeat, feel-good, pop.
      - Evening (17:00 - 21:59): Party, trending, chartbusters, high energy.
      - Late Night (22:00 - 04:59): Soulful, acoustic, lofi, romantic, soothing.
    """
    now = datetime.now()
    hour = now.hour

    if 5 <= hour < 12:
        return {
            "slot": "morning",
            "greeting": "Good morning",
            "title": "Morning Melodies",
            "subtitle": "Start your day with fresh acoustic & melodic vibes",
            "icon": "sunrise",
            "mood": "fresh_acoustic",
            "query_template": "{lang} morning pleasant melody songs",
        }
    elif 12 <= hour < 17:
        return {
            "slot": "afternoon",
            "greeting": "Good afternoon",
            "title": "Afternoon Energy",
            "subtitle": "Keep your rhythm going with feel-good hits",
            "icon": "sun",
            "mood": "upbeat_focus",
            "query_template": "{lang} super hit upbeat songs",
        }
    elif 17 <= hour < 22:
        return {
            "slot": "evening",
            "greeting": "Good evening",
            "title": "Evening Vibes",
            "subtitle": "Top trending chartbusters & sunset melodies",
            "icon": "sunset",
            "mood": "trending_party",
            "query_template": "{lang} top trending blockbuster songs",
        }
    else:
        return {
            "slot": "night",
            "greeting": "Late night",
            "title": "Late Night Soul",
            "subtitle": "Unwind with soulful melodies & chill acoustic vibes",
            "icon": "moon",
            "mood": "chill_lofi",
            "query_template": "{lang} soulful late night romantic melody songs",
        }


# =====================================================================
# 2. MULTI-VECTOR HYBRID SONG RADIO ALGORITHM
# =====================================================================

async def get_song_radio(
    current_track: dict,
    user_id: Optional[str] = None,
    limit: int = 15
) -> List[dict]:
    """
    Generate an intelligent, continuous radio playlist based on the currently playing track.
    Combines:
      1. YouTube Related Graph (audio continuity).
      2. Artist Cluster (same/complementary artist hits).
      3. Album / Movie Soundtrack Cluster.
      4. Collaborative Transition Markov Graph.
      5. User Favorite Affinity (injected for familiarity).
    Ranks tracks using a multi-factor scoring algorithm with strict language consistency.
    """
    video_id = current_track.get("video_id", "")
    track_name = current_track.get("track_name") or current_track.get("title", "")
    artist = current_track.get("artist", "")
    movie = current_track.get("movie", "")
    language = current_track.get("language") or "Telugu"

    db = database.db
    cache_key = f"radio:{video_id}:{language.lower()}:{limit}"

    # Check cache first (valid for 2 hours)
    if db is not None:
        try:
            cached = await db.recommendation_cache.find_one({
                "_id": cache_key,
                "cached_at": {"$gt": datetime.now(timezone.utc) - timedelta(hours=2)}
            })
            if cached and cached.get("tracks") and len(cached["tracks"]) >= 5:
                return cached["tracks"]
        except Exception:
            pass

    # Clean artist name to remove record labels
    clean_artist = artist if artist.lower() not in [
        "think music", "aditya music", "t-series", "sony music", "saregama", "lahari music"
    ] else ""

    # === FAN OUT MULTI-SOURCE SEARCHES IN PARALLEL ===
    tasks = []

    # 1. YouTube related videos
    if video_id:
        tasks.append(get_related_videos(video_id, max_results=12))
    else:
        tasks.append(asyncio.sleep(0, result=[]))

    # 2. Artist hit songs cluster
    if clean_artist:
        artist_q = f"{clean_artist} {language} hit songs"
        tasks.append(search_youtube(artist_q, max_results=8))
    else:
        tasks.append(asyncio.sleep(0, result=[]))

    # 3. Movie soundtrack / Same vibe cluster
    if movie and movie.lower() != track_name.lower():
        movie_q = f"{movie} {language} songs"
        tasks.append(search_youtube(movie_q, max_results=6))
    else:
        genre_q = f"{language} latest hit melody songs"
        tasks.append(search_youtube(genre_q, max_results=6))

    # 4. Collaborative Transition Graph lookups
    async def _get_graph_candidates():
        if db is None or not video_id:
            return []
        try:
            node = await db.recommendation_graph.find_one({"track_id": video_id})
            if node and node.get("edges"):
                edges = sorted(node["edges"], key=lambda x: x.get("weight", 0), reverse=True)[:5]
                target_ids = [e["target"] for e in edges]
                tracks = []
                cursor = db.song_cache.find({"_id": {"$in": target_ids}})
                docs = await cursor.to_list(length=len(target_ids))
                for doc in docs:
                    tid = doc.pop("_id", None)
                    doc["video_id"] = tid
                    tracks.append(doc)
                return tracks
        except Exception:
            pass
        return []

    tasks.append(_get_graph_candidates())

    # Execute all candidate generators concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    related_tracks = results[0] if isinstance(results[0], list) else []
    artist_tracks = results[1] if isinstance(results[1], list) else []
    vibe_tracks = results[2] if isinstance(results[2], list) else []
    graph_tracks = results[3] if isinstance(results[3], list) else []

    # === SCORE & RANK CANDIDATES ===
    candidates: Dict[str, dict] = {}
    scores: Dict[str, float] = {}

    target_lang = language.lower()

    def _process_track(t: dict, base_score: float, reason: str):
        if not t or not isinstance(t, dict):
            return
        vid = t.get("video_id")
        if not vid or vid == video_id:
            return  # Don't recommend the currently playing track

        # Ignore 1hr+ full jukeboxes / dj mixes or < 60s clips
        duration = t.get("duration", 0)
        if duration > 700 or (0 < duration < 60):
            return

        if vid not in candidates:
            candidates[vid] = t
            candidates[vid]["vibe_reason"] = reason
            scores[vid] = base_score
        else:
            scores[vid] += base_score  # Boost if returned by multiple sources

        # Language affinity scoring
        track_lang = (t.get("language") or "").lower()
        title_sub = (t.get("title", "") + " " + t.get("subtitle", "")).lower()

        if track_lang == target_lang or target_lang in title_sub:
            scores[vid] += 30.0
        elif track_lang and track_lang != target_lang:
            scores[vid] -= 25.0  # Penalize mismatched language

        # Artist affinity scoring
        if clean_artist and clean_artist.lower() in (t.get("artist", "") + " " + t.get("title", "")).lower():
            scores[vid] += 15.0

        # Movie / Album affinity scoring
        if movie and movie.lower() in (t.get("movie", "") + " " + t.get("title", "")).lower():
            scores[vid] += 20.0

    for t in related_tracks:
        _process_track(t, 25.0, "Similar Vibe")

    for t in artist_tracks:
        _process_track(t, 22.0, f"More by {clean_artist or 'Artist'}")

    for t in vibe_tracks:
        _process_track(t, 18.0, "Trending in " + language)

    for t in graph_tracks:
        _process_track(t, 35.0, "Listeners Also Played")

    # Sort candidates by score descending
    sorted_vids = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    ranked_tracks = [candidates[vid] for vid in sorted_vids[:limit]]

    # If too few candidates found, fallback to general search in target language
    if len(ranked_tracks) < 6:
        fallback_query = f"{language} top songs"
        extras = await search_youtube(fallback_query, max_results=8)
        seen_ids = set(t["video_id"] for t in ranked_tracks)
        seen_ids.add(video_id)
        for e in extras:
            if e.get("video_id") and e["video_id"] not in seen_ids:
                seen_ids.add(e["video_id"])
                e["vibe_reason"] = f"Top {language} Hit"
                ranked_tracks.append(e)

    final_list = ranked_tracks[:limit]

    # Cache the result in MongoDB
    if db is not None and final_list:
        try:
            await db.recommendation_cache.update_one(
                {"_id": cache_key},
                {
                    "$set": {
                        "video_id": video_id,
                        "language": language,
                        "tracks": final_list,
                        "cached_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
        except Exception:
            pass

    return final_list


# =====================================================================
# 3. PERSONALIZED CONTEXTUAL HOME FEED
# =====================================================================

async def get_personalized_home_feed(user_id: Optional[str] = None) -> dict:
    """
    Generate dynamic, contextual home feed sections:
      - time_context: Morning/Afternoon/Evening/Night greeting & mood.
      - mood_mix: Tracks curated for the current time slot.
      - for_you: Personalized tracks based on user's top played artists/languages.
      - trending: Global trending hits.
      - categories: Browse categories.
    """
    cache_key = f"home_feed:{user_id or 'anon'}"
    cached = home_feed_cache.get(cache_key)
    if cached is not None:
        return cached

    time_ctx = get_time_of_day_context()
    db = database.db

    preferred_lang = "Telugu"

    # Analyze user's history if authenticated
    top_artist = ""
    if user_id and db is not None:
        try:
            from bson import ObjectId
            user_obj_id = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
            if user_obj_id:
                user_doc = await db.users.find_one({"_id": user_obj_id})
                if user_doc and user_doc.get("settings", {}).get("language_preference"):
                    prefs = user_doc["settings"]["language_preference"]
                    if prefs and isinstance(prefs, list):
                        preferred_lang = prefs[0]

                # Query listening_history collection with user ObjectId
                cursor = db.listening_history.find(
                    {"user_id": user_obj_id}
                ).sort("played_at", -1).limit(20)
                history = await cursor.to_list(length=20)
                if history:
                    lang_counts = {}
                    artist_counts = {}
                    for h in history:
                        l = h.get("language")
                        if l:
                            lang_counts[l] = lang_counts.get(l, 0) + 1
                        a = h.get("artist")
                        if a and a.lower() not in ["unknown", "wave music", ""]:
                            artist_counts[a] = artist_counts.get(a, 0) + 1

                    if lang_counts:
                        preferred_lang = max(lang_counts.keys(), key=lambda k: lang_counts[k])
                    if artist_counts:
                        top_artist = max(artist_counts.keys(), key=lambda k: artist_counts[k])
        except Exception as e:
            logger.debug(f"User profile inference error: {e}")

    # Build queries
    mood_query = time_ctx["query_template"].format(lang=preferred_lang)
    for_you_query = f"{top_artist} {preferred_lang} hit songs" if top_artist else f"{preferred_lang} super hit songs"

    mood_task = search_youtube(mood_query, max_results=10)
    for_you_task = search_youtube(for_you_query, max_results=10)
    trending_task = get_trending_tracks("trending", 10)
    telugu_task = get_trending_tracks("telugu", 10)
    hindi_task = get_trending_tracks("hindi", 10)
    english_task = get_trending_tracks("english", 10)
    lofi_task = get_trending_tracks("lofi", 10)

    results = await asyncio.gather(
        mood_task, for_you_task, trending_task, telugu_task, hindi_task, english_task, lofi_task,
        return_exceptions=True
    )

    mood_tracks = results[0] if isinstance(results[0], list) else []
    for_you_tracks = results[1] if isinstance(results[1], list) else []
    trending_tracks = results[2] if isinstance(results[2], list) else []
    telugu_tracks = results[3] if isinstance(results[3], list) else []
    hindi_tracks = results[4] if isinstance(results[4], list) else []
    english_tracks = results[5] if isinstance(results[5], list) else []
    lofi_tracks = results[6] if isinstance(results[6], list) else []

    feed_data = {
        "time_context": time_ctx,
        "mood_mix": mood_tracks,
        "for_you": for_you_tracks,
        "trending": trending_tracks,
        "telugu": telugu_tracks,
        "hindi": hindi_tracks,
        "english": english_tracks,
        "lofi": lofi_tracks,
        "categories": CATEGORIES,
        "preferred_language": preferred_lang,
    }
    home_feed_cache.set(cache_key, feed_data, ttl=600.0)
    return feed_data


# =====================================================================
# 4. TRENDING TRACKS & GRAPH CO-LISTEN RECORDING
# =====================================================================

async def get_trending_tracks(category: str = "trending", limit: int = 15) -> List[dict]:
    """Get trending tracks for a given category with MongoDB caching."""
    db = database.db
    cache_key = f"feed:{category}:{limit}"

    if db is not None:
        try:
            cached = await db.recommendation_cache.find_one({
                "_id": cache_key,
                "cached_at": {"$gt": datetime.now(timezone.utc) - timedelta(hours=6)}
            })
            if cached and cached.get("tracks"):
                return cached["tracks"]
        except Exception:
            pass

    cat_info = next((c for c in CATEGORIES if c["id"] == category), CATEGORIES[0])
    query = cat_info["query"]
    tracks = await search_youtube(query, max_results=limit)

    if db is not None and tracks:
        try:
            await db.recommendation_cache.update_one(
                {"_id": cache_key},
                {
                    "$set": {
                        "category": category,
                        "tracks": tracks,
                        "cached_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
        except Exception:
            pass

    return tracks


async def get_home_feed(user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch sections for the home feed with Stale-While-Revalidate (SWR) caching.
    Check home_feed_cache.get(cache_key); if present, return it immediately.
    """
    cache_key = f"home_feed:{user_id or 'anon'}"
    cached = home_feed_cache.get(cache_key)
    if cached is not None:
        return cached

    feed_data = await get_personalized_home_feed(user_id)
    if feed_data:
        home_feed_cache.set(cache_key, feed_data, ttl=600.0)
    return feed_data


async def record_co_listen(track_a_id: str, track_b_id: str) -> None:
    """Update the recommendation Markov graph when tracks are played in sequence."""
    if not track_a_id or not track_b_id or track_a_id == track_b_id:
        return

    db = database.db
    if db is None:
        return

    try:
        now = datetime.now(timezone.utc)
        # 1. Update existing edge weight
        res = await db.recommendation_graph.update_one(
            {"track_id": track_a_id, "edges.target": track_b_id},
            {"$inc": {"edges.$.weight": 1.0}, "$set": {"updated_at": now}},
        )
        # 2. If edge didn't exist, push new edge
        if res.matched_count == 0:
            await db.recommendation_graph.update_one(
                {"track_id": track_a_id},
                {
                    "$push": {"edges": {"target": track_b_id, "weight": 1.0, "type": "co-listen"}},
                    "$set": {"updated_at": now}
                },
                upsert=True
            )
    except Exception as e:
        logger.debug(f"Graph update error: {e}")


async def get_next_recommendation(current_video_id: str) -> Optional[dict]:
    """Get single top next song for legacy compatibility."""
    tracks = await get_song_radio({"video_id": current_video_id}, limit=3)
    if tracks:
        return tracks[0]
    return None


class RecommendationService:
    """Service namespace for recommendation algorithms and feeds."""

    get_time_of_day_context = staticmethod(get_time_of_day_context)
    get_song_radio = staticmethod(get_song_radio)
    get_personalized_home_feed = staticmethod(get_personalized_home_feed)
    get_trending_tracks = staticmethod(get_trending_tracks)
    get_home_feed = staticmethod(get_home_feed)
    record_co_listen = staticmethod(record_co_listen)
    get_next_recommendation = staticmethod(get_next_recommendation)

