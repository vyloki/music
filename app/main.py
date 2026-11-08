"""
Wave - FastAPI Application Entry Point
Main application setup with CORS, static files, lifespan, and route registration.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from bson.errors import InvalidId
from app.config import settings
from app.database import database
from app.tasks import shutdown_background_tasks
from app.services.http_client import close_http_clients
from app.utils.cache import health_cache
import logging
import os

# Configure logging
log_level = logging.DEBUG if settings.debug else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)

# Silence noisy third-party loggers (PyMongo heartbeat floods, passlib, httpx connection traces)
NOISY_LOGGERS = [
    "pymongo",
    "pymongo.topology",
    "pymongo.serverSelection",
    "pymongo.connection",
    "pymongo.command",
    "passlib",
    "urllib3",
    "asyncio",
    "httpcore",
    "httpx",
    "watchfiles",
]
for logger_name in NOISY_LOGGERS:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

logger = logging.getLogger("wave")
logging.getLogger("app").setLevel(log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # === STARTUP ===
    logger.info("🎵 Starting Wave Music App...")
    logger.info(f"   Version: {settings.app_version}")
    logger.info(f"   Debug: {settings.debug}")

    # Connect to MongoDB
    try:
        await database.connect()
    except Exception as e:
        logger.warning(
            f"⚠️ MongoDB connection failed on startup: {e}\n"
            f"   Please ensure 0.0.0.0/0 is added to MongoDB Atlas Network Access."
        )

    logger.info(
        f"🚀 Wave is ready at "
        f"http://{settings.host}:{settings.port}"
    )

    yield  # Application is running

    # === SHUTDOWN ===
    logger.info("🛑 Shutting down Wave...")
    try:
        await shutdown_background_tasks(timeout=2.0)
    except Exception as e:
        logger.debug(f"Background task shutdown: {e}")

    await database.disconnect()
    try:
        await close_http_clients()
    except Exception as e:
        logger.debug(f"HTTP clients shutdown: {e}")
    logger.info("👋 Wave stopped gracefully")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="🎵 Wave — Your Personal Music Streaming App",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS Middleware — allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Type", "Accept-Encoding"],
)

# --- API Routes ---
from app.routes import auth, search, stream, playlist, history, lyrics, recommendations, artists, songs, extract
app.include_router(auth.router)
app.include_router(search.router)
app.include_router(stream.router)
app.include_router(playlist.router)
app.include_router(history.router)
app.include_router(lyrics.router)
app.include_router(recommendations.router)
app.include_router(artists.router)
app.include_router(songs.router)
app.include_router(extract.router)

# Health check endpoint
@app.get("/api/health", tags=["System"])
async def health_check():
    """Health check endpoint to verify the server and database are running."""
    cached = health_cache.get("health")
    if cached is not None:
        return cached

    db_status = "disconnected"
    if database.client is not None:
        try:
            await database.client.admin.command("ping")
            db_status = "connected"
        except Exception:
            db_status = "disconnected"

    result = {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "database": db_status,
    }
    health_cache.set("health", result, ttl=5.0)
    return result


# Global exception handler for invalid MongoDB ObjectIds
@app.exception_handler(InvalidId)
async def invalid_id_handler(request: Request, exc: InvalidId):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Invalid resource ID format"},
    )


# --- Static Files & Frontend Serving ---
# Serve the frontend directory as static files
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.exists(frontend_dir):
    # Serve static assets (CSS, JS, images)
    app.mount(
        "/static",
        StaticFiles(directory=frontend_dir),
        name="static",
    )

    # Serve index.html for the root path (SPA)
    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        """Serve the frontend SPA."""
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "🎵 Wave API is running. Frontend not found."}
else:
    @app.get("/", include_in_schema=False)
    async def root():
        """Root endpoint when frontend is not yet built."""
        return {
            "message": "🎵 Wave API is running",
            "docs": "/docs",
            "health": "/api/health",
        }
