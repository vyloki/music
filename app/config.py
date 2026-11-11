"""
Wave - Centralized Application Configuration
Loads settings from .env file using Pydantic Settings.
"""

from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices, field_validator
from typing import List, Union


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = Field(default="Wave", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, v):
        if isinstance(v, str):
            v_low = v.strip().lower()
            if v_low in ("true", "1", "yes", "on", "t"):
                return True
            if v_low in ("false", "0", "no", "off", "f"):
                return False
            # Handle non-boolean strings like log levels "WARN", "INFO" safely in production
            return False
        return bool(v)
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # MongoDB
    mongodb_uri: str = Field(
        default="mongodb://localhost:27017",
        alias="MONGODB_URI"
    )
    mongodb_db_name: str = Field(default="wave_db", alias="MONGODB_DB_NAME")

    # JWT Authentication
    jwt_secret_key: str = Field(
        default="change-this-secret-key",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "JWT_SECRET")
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=60,
        alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=30,
        alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # Last.fm API
    lastfm_api_key: str = Field(default="", alias="LASTFM_API_KEY")
    lastfm_api_secret: str = Field(default="", alias="LASTFM_API_SECRET")

    # CORS
    cors_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000",
        alias="CORS_ORIGINS"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


# Singleton settings instance
settings = Settings()
