"""Application configuration settings."""
from functools import lru_cache
from typing import Optional

from pydantic.v1 import BaseSettings, Field


class Settings(BaseSettings):
    """Configuration values loaded from environment variables."""

    app_name: str = Field(default="graph-mem-chat-backend", description="Service name")
    ollama_base_url: str = Field(
        default="http://host.containers.internal:11434",
        description="Base URL for the Ollama service",
    )
    ollama_model: str = Field(default="gpt-oss-20b", description="Name of the Ollama model")
    neo4j_uri: str = Field(default="neo4j://neo4j:7687", description="Neo4j bolt URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j username")
    neo4j_password: str = Field(default="neo4j", description="Neo4j password")
    short_term_ttl_minutes: int = Field(
        default=60, description="Time-to-live for short-term memory nodes"
    )
    allow_origins: list[str] = Field(default_factory=lambda: ["*"], description="CORS origins")
    nginx_host: Optional[str] = Field(
        default=None, description="Optional upstream host for Nginx health checks"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""

    return Settings()
