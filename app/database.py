"""
Wave - MongoDB Async Database Connection
Uses Motor (async MongoDB driver) with connection pooling.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings
import logging
import certifi

logger = logging.getLogger(__name__)


class Database:
    """MongoDB async database manager with connection pooling."""

    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None

    async def connect(self) -> None:
        """Establish connection to MongoDB Atlas."""
        try:
            ca_file = certifi.where()
            self.client = AsyncIOMotorClient(
                settings.mongodb_uri,
                maxPoolSize=10,
                minPoolSize=1,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
                tlsCAFile=ca_file,
            )
            self.db = self.client[settings.mongodb_db_name]

            # Verify connection by pinging the server
            await self.client.admin.command("ping")
            logger.info(
                f"✅ Connected to MongoDB Atlas — "
                f"Database: {settings.mongodb_db_name}"
            )

            # Create indexes for performance
            await self._create_indexes()

        except Exception as e:
            logger.error(f"❌ Failed to connect to MongoDB: {e}")
            raise

    async def _create_indexes(self) -> None:
        """Create database indexes with per-index isolation and TTL expiration."""
        index_definitions = [
            # Users collection
            ("users", "email", {"unique": True}),
            ("users", "username", {"unique": True}),

            # Playlists collection
            ("playlists", "user_id", {}),

            # Listening history
            ("listening_history", [("user_id", 1), ("played_at", -1)], {}),
            ("listening_history", [("user_id", 1), ("video_id", 1)], {}),

            # Daily tracking
            ("daily_tracking", [("user_id", 1), ("date", 1)], {}),

            # Liked songs
            ("liked_songs", [("user_id", 1), ("liked_at", -1)], {}),
            ("liked_songs", [("user_id", 1), ("video_id", 1)], {}),

            # Recommendation graph
            ("recommendation_graph", "track_id", {"unique": True}),

            # Link extraction history
            ("link_history", [("user_id", 1), ("extracted_at", -1)], {}),

            # Revoked tokens (for logout / token rotation)
            ("revoked_tokens", "token", {"unique": True}),
            ("revoked_tokens", "revoked_at", {"expireAfterSeconds": 86400 * 30}),

            # TTL Caches: automatic pruning of expired entries
            ("stream_cache", "expires_at", {"expireAfterSeconds": 0}),
            ("search_cache", "cached_at", {"expireAfterSeconds": 86400 * 2}),
            ("recommendation_cache", "cached_at", {"expireAfterSeconds": 86400}),
            ("song_cache", "cached_at", {"expireAfterSeconds": 86400 * 7}),
            ("lyrics_cache", "cached_at", {"expireAfterSeconds": 86400 * 30}),
        ]

        for coll_name, keys, kwargs in index_definitions:
            try:
                coll = self.db[coll_name]
                await coll.create_index(keys, **kwargs)
            except Exception as e:
                logger.debug(f"Index creation note for {coll_name} ({keys}): {e}")

        logger.info("✅ Database indexes verified and created")

    async def disconnect(self) -> None:
        """Close the MongoDB connection cleanly."""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            logger.info("🔌 Disconnected from MongoDB")

    def get_collection(self, name: str):
        """Get a MongoDB collection by name."""
        return self.db[name]


# Singleton database instance
database = Database()


def get_db() -> AsyncIOMotorDatabase:
    """Dependency injection helper to get the database instance."""
    return database.db
