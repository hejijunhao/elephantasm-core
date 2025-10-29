"""Application configuration via Pydantic Settings."""

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # API Settings
    PROJECT_NAME: str = "Elephantasm API"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"

    # Database Settings
    # Plain PostgreSQL URLs (Supabase standard format)
    # Driver (+psycopg) is added programmatically in database.py
    DATABASE_URL: str  # Runtime: Transaction pooler (port 6543)
    MIGRATION_DATABASE_URL: str  # Migrations: Direct connection (port 5432)

    # LLM Configuration
    ANTHROPIC_API_KEY: str = ""  # Required for Anthropic/Claude
    OPENAI_API_KEY: str = ""     # Required for OpenAI/GPT

    # CORS Settings
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ]


# Global settings instance
settings = Settings()
