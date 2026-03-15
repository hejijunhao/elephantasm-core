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
    CRON_DATABASE_URL: str = ""  # Scheduler: BYPASSRLS role for cron jobs (port 6543)

    # Supabase Configuration
    SUPABASE_URL: str = ""  # Required for JWKS-based JWT verification (fetches public keys from /.well-known/jwks.json)

    # LLM Configuration
    ANTHROPIC_API_KEY: str = ""  # Required for Anthropic/Claude
    OPENAI_API_KEY: str = ""     # Required for OpenAI/GPT

    # CORS Settings
    BACKEND_CORS_ORIGINS: List[str]

    # Background Jobs
    ENABLE_BACKGROUND_JOBS: bool = True  # Set false locally to avoid firing against prod

    # Admin Configuration
    ADMIN_EMAILS: List[str] = []  # Emails with admin access

    # Stripe Integration
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_TEAM: str = ""

    # Stripe Overage Products (one-time products for invoice line items)
    STRIPE_PRODUCT_OVERAGE_EVENTS: str = ""
    STRIPE_PRODUCT_OVERAGE_MEMORIES: str = ""
    STRIPE_PRODUCT_OVERAGE_KNOWLEDGE: str = ""
    STRIPE_PRODUCT_OVERAGE_PACK_BUILDS: str = ""
    STRIPE_PRODUCT_OVERAGE_SYNTHESIS: str = ""

    def get_stripe_price(self, tier: str) -> str:
        """Map plan tier to Stripe price ID."""
        prices = {
            "pro": self.STRIPE_PRICE_PRO,
            "team": self.STRIPE_PRICE_TEAM,
        }
        price = prices.get(tier, "")
        if not price:
            raise ValueError(f"No Stripe price configured for tier: {tier}")
        return price

    def get_overage_product(self, resource: str) -> str:
        """Map resource name to Stripe overage product ID."""
        products = {
            "events": self.STRIPE_PRODUCT_OVERAGE_EVENTS,
            "memories": self.STRIPE_PRODUCT_OVERAGE_MEMORIES,
            "knowledge": self.STRIPE_PRODUCT_OVERAGE_KNOWLEDGE,
            "pack_builds": self.STRIPE_PRODUCT_OVERAGE_PACK_BUILDS,
            "synthesis": self.STRIPE_PRODUCT_OVERAGE_SYNTHESIS,
        }
        product = products.get(resource, "")
        if not product:
            raise ValueError(f"No Stripe overage product configured for: {resource}")
        return product


# Global settings instance
settings = Settings()
