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
    VERSION: str = "0.5.8"
    API_PREFIX: str = "/api"

    # Database Settings
    # Plain PostgreSQL URLs (Supabase standard format)
    # Driver (+psycopg) is added programmatically in database.py
    DATABASE_URL: str  # Runtime: Transaction pooler (port 6543)
    MIGRATION_DATABASE_URL: str  # Migrations: Direct connection (port 5432)

    def get_database_url_for_async(self) -> str:
        """
        Get DATABASE_URL for async psycopg connections (LangGraph AsyncPostgresSaver).

        DISCARD ALL event listener in database.py handles pgBouncer prepared statement cleanup.
        """
        return self.DATABASE_URL

    # Supabase Configuration
    SUPABASE_URL: str = ""  # Required for JWKS-based JWT verification (fetches public keys from /.well-known/jwks.json)

    # LLM Configuration
    ANTHROPIC_API_KEY: str = ""  # Required for Anthropic/Claude
    OPENAI_API_KEY: str = ""     # Required for OpenAI/GPT

    # LangSmith Tracing (Optional - for debugging/monitoring)
    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = ""
    LANGSMITH_ENDPOINT: str = ""

    # CORS Settings
    BACKEND_CORS_ORIGINS: List[str]

    # Background Jobs
    ENABLE_BACKGROUND_JOBS: bool = True  # Set false locally to avoid firing against prod

    # Admin Configuration
    ADMIN_EMAILS: List[str] = []  # Emails with admin access


# Global settings instance
settings = Settings()
